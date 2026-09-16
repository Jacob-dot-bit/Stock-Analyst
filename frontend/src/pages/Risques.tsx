import { Drawdown } from '../components/Drawdown'
import { FactorExposures } from '../components/FactorExposures'
import { Liquidity } from '../components/Liquidity'
import { PortfolioBreakdown } from '../components/PortfolioBreakdown'
import { PositionConcentration } from '../components/PositionConcentration'
import { useI18n } from '../i18n'

/**
 * "What is my portfolio actually exposed to" — unconditional exposure
 * facts, never gated behind a configured limit and never a duplicate of
 * what Personal Policy already shows. Policy answers "did I breach the
 * limit I chose?"; this page answers a genuinely different question. See
 * DEVLOG "Decision 3u.67".
 *
 * Reunites two facets that already shipped on the Portfolio page
 * (`PortfolioBreakdown`, `FactorExposures` — moved here unchanged, not
 * duplicated) with three new ones (line-level concentration, liquidity/
 * declared-valuation share, historical max drawdown).
 */
export function Risques() {
  const { t } = useI18n()

  return (
    <>
      <div className="page-header">
        <h1>{t('risk.title')}</h1>
        <p>{t('risk.subtitle')}</p>
      </div>

      <div className="notice info">{t('risk.disclaimer')}</div>

      <PortfolioBreakdown />
      <PositionConcentration />
      <Liquidity />
      <Drawdown />
      <FactorExposures />
    </>
  )
}
