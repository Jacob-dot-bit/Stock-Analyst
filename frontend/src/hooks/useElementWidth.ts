import { useEffect, useState } from 'react'

/** Tracks an element's rendered width, so an SVG chart can be drawn at its
 * real pixel size instead of a fixed viewBox stretched to fit — stretching
 * scales the axis text with the window (huge labels on a wide monitor, tiny
 * ones on a phone). Returns a callback ref, so it also works for an element
 * that only mounts once its data has loaded. */
export function useElementWidth<T extends HTMLElement>() {
  const [element, setElement] = useState<T | null>(null)
  const [width, setWidth] = useState(0)

  useEffect(() => {
    if (!element) return
    setWidth(element.clientWidth)
    const observer = new ResizeObserver((entries) => {
      const next = Math.round(entries[0].contentRect.width)
      setWidth((previous) => (previous === next ? previous : next))
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [element])

  return [setElement, width] as const
}
