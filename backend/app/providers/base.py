"""Pluggable market-data providers, with an ordered fallback chain.

Free price sources are fragile by nature: they rate-limit aggressively, change
undocumented endpoints, and occasionally disappear behind anti-bot walls. The whole
application therefore talks to this interface and never to a specific provider, so a
source can be swapped without touching the analysis code.

Two rules the chain enforces:

* **The provider that actually served the data is recorded**, and surfaced in the UI.
  "Where did this number come from?" must always have an answer.
* **A failure is described, not swallowed.** Each attempt returns a reason code —
  rate-limited, symbol unknown, network error — so the user can tell "this instrument
  does not exist at this provider" from "come back in ten minutes".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class InstrumentRef:
    """Every identifier a provider might need to find an instrument.

    Providers do not share a namespace: Yahoo wants a ticker with a venue suffix,
    Twelve Data a bare ticker, Boerse Frankfurt an ISIN and nothing else. Passing a
    single "symbol" string forced every provider to pretend they agreed, so each one
    now takes the whole reference and picks what it needs — raising SymbolNotFound
    when its identifier is missing.
    """

    provider_symbol: str | None = None
    isin: str | None = None
    broker_symbol: str | None = None
    #: The company or fund name the broker reported. Providers that echo a name in
    #: their response use it to confirm they answered about the right instrument.
    name: str | None = None
    #: Broker category (STOCK, ETF, CFD), which some providers need to pick a namespace.
    category: str | None = None


@dataclass(frozen=True)
class Bar:
    """One daily candle, in the instrument's own currency."""

    bar_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


#: Broker suffixes that denote a US listing. Used for routing, never for identity.
US_SUFFIXES = ("US",)


def is_us_listing(ref: "InstrumentRef") -> bool:
    """Whether the instrument trades on a US venue, from its broker symbol."""
    symbol = (ref.broker_symbol or "").upper()
    return symbol.rpartition(".")[2] in US_SUFFIXES if "." in symbol else False


class ProviderError(Exception):
    """Base class for provider failures. Carries a machine-readable reason."""

    reason = "failed"


class SymbolNotFound(ProviderError):
    """The provider does not know this symbol — retrying will not help."""

    reason = "symbol_not_found"


class RateLimited(ProviderError):
    """The provider is throttling us. Retrying later may help; retrying now will not."""

    reason = "rate_limited"


class PlanLimited(ProviderError):
    """The provider knows this symbol but the current plan does not include it.

    Distinct from SymbolNotFound: the symbol is correct and there is nothing to fix
    locally. Telling the user to check their mapping would send them chasing a
    problem that does not exist.
    """

    reason = "plan_limited"


class ProviderUnavailable(ProviderError):
    """Network failure, or the provider is not configured."""

    reason = "unavailable"


@runtime_checkable
class PriceProvider(Protocol):
    """A source of daily price history."""

    name: str

    def is_enabled(self) -> bool:
        """False when the provider lacks configuration (an API key, typically)."""
        ...

    def can_serve(self, ref: InstrumentRef) -> bool:
        """Whether this provider could plausibly answer for this instrument.

        Lets the chain skip calls that are known to fail. A French holding sent to a
        US-only free tier costs a request, a few seconds, and returns a plan error
        every time — quota spent to learn something already known.

        Answering ``True`` is always safe: the call simply happens and may fail.
        """
        ...


@dataclass
class Attempt:
    provider: str
    reason: str | None = None  # None means it succeeded


@dataclass
class FetchResult:
    bars: list[Bar] = field(default_factory=list)
    provider: str | None = None
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.provider is not None

    @property
    def rate_limited(self) -> bool:
        """True when every provider that tried was throttling.

        Distinguished from a plain failure because it means "try again later",
        not "this instrument cannot be fetched".
        """
        return bool(self.attempts) and all(a.reason == RateLimited.reason for a in self.attempts)


class Throttle:
    """Minimum spacing between calls to one provider.

    Deliberately process-wide and blocking: free endpoints ban bursts far more
    readily than they ban steady traffic, and a refresh is not latency-sensitive.
    """

    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval = min_interval_seconds
        # None rather than 0.0: "never called" is a distinct state from "called at
        # time zero". Relying on monotonic() being large enough would work in practice
        # and be wrong in principle — and it would make the first call sleep for
        # nothing under any clock that starts near zero.
        self._last_call: float | None = None

    def wait(self) -> None:
        if self.min_interval <= 0:
            return

        now = time.monotonic()
        if self._last_call is not None:
            elapsed = now - self._last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
                now = time.monotonic()

        self._last_call = now


class Cooldown:
    """Stops asking a provider that has just told us to stop.

    A rate limit is a request to back off, and hammering through it is what turns a
    short throttle into a long block. Once a provider answers 429, it is left alone for
    a while instead of being retried on every one of the next thirty instruments —
    which is both the polite behaviour and the one most likely to get us unblocked.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._until: dict[str, float] = {}

    def start(self, provider_name: str) -> None:
        self._until[provider_name] = time.monotonic() + self.seconds

    def is_active(self, provider_name: str) -> bool:
        until = self._until.get(provider_name)
        if until is None:
            return False
        if time.monotonic() >= until:
            del self._until[provider_name]
            return False
        return True

    def remaining(self, provider_name: str) -> float:
        until = self._until.get(provider_name)
        return max(0.0, until - time.monotonic()) if until else 0.0


class ProviderChain:
    """Tries each provider in order and reports what happened at every step."""

    def __init__(self, providers: list[PriceProvider], cooldown_seconds: float = 900.0) -> None:
        self.providers = providers
        self.cooldown = Cooldown(cooldown_seconds)

    def enabled_providers(self) -> list[PriceProvider]:
        return [p for p in self.providers if p.is_enabled()]

    def fetch_daily(self, ref: InstrumentRef, start: date, end: date) -> FetchResult:
        result = FetchResult()

        for provider in self.enabled_providers():
            # Honour an earlier "slow down" instead of asking again immediately.
            if self.cooldown.is_active(provider.name):
                result.attempts.append(Attempt(provider.name, RateLimited.reason))
                continue

            # Skip providers that cannot serve this market at all. Not recorded as an
            # attempt: nothing was attempted, and listing it would bury the real
            # reasons under noise.
            if not provider.can_serve(ref):
                continue

            try:
                bars = provider.fetch_daily(ref, start, end)
            except RateLimited as exc:
                self.cooldown.start(provider.name)
                result.attempts.append(Attempt(provider.name, exc.reason))
                continue
            except ProviderError as exc:
                result.attempts.append(Attempt(provider.name, exc.reason))
                continue
            except Exception:  # noqa: BLE001 - an unexpected bug must not kill a refresh
                result.attempts.append(Attempt(provider.name, ProviderError.reason))
                continue

            if not bars:
                # An empty answer is not an error, but it is not usable either:
                # move on rather than declaring success with nothing to show.
                result.attempts.append(Attempt(provider.name, SymbolNotFound.reason))
                continue

            result.attempts.append(Attempt(provider.name))
            result.bars = bars
            result.provider = provider.name
            return result

        return result
