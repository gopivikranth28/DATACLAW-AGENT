import { useState } from 'react'
import { Tag, Tooltip } from 'antd'

/**
 * The compact trust row on a report card: rubric quality, browser evidence,
 * visual review, fact verification, and normalization provenance. A skipped
 * browser check must be visibly different from a passed one, and a
 * low-confidence preservation must be visibly different from a clean rebuild.
 */

export interface QualityResult {
  status?: 'pass' | 'warn' | 'fail' | 'off' | string
  rubric_version?: number
  warnings?: { code?: string; severity?: string; message?: string }[]
}

export interface RuntimeSmoke {
  status?: 'passed' | 'failed' | 'skipped' | 'static' | string
  reason?: string
  checks?: { check?: string; detail?: string }[]
}

export interface VisualReviewSummary {
  required?: boolean
  status?: string
  reviewer?: string | null
  review_path?: string | null
}

export interface FactVerification {
  status?: 'pass' | 'fail' | string
  fact_count?: number
  bound_fact_count?: number
  binding_count?: number
  unbound_numeral_count?: number
  findings?: { id?: string; claim?: string }[]
}

export interface NormalizationSummary {
  mode?: string
  confidence?: number
  authoring_tier?: string
}

export default function ReportTrustStrip({ quality, runtimeSmoke, visualReview, factVerification, normalization }: {
  quality?: QualityResult
  runtimeSmoke?: RuntimeSmoke
  visualReview?: VisualReviewSummary
  factVerification?: FactVerification
  normalization?: NormalizationSummary
}) {
  const [expanded, setExpanded] = useState<'quality' | 'smoke' | null>(null)

  const qualityTag = qualityTagProps(quality)
  const smokeTag = smokeTagProps(runtimeSmoke)
  const visualTag = visualTagProps(visualReview)
  const factsTag = factsTagProps(factVerification)
  const normalizationTag = normalizationTagProps(normalization)
  if (!qualityTag && !smokeTag && !visualTag && !factsTag && !normalizationTag) return null

  const qualityWarnings = quality?.warnings?.filter(w => w?.message || w?.code) || []
  const smokeChecks = runtimeSmoke?.checks?.filter(c => c?.detail || c?.check) || []

  const toggle = (key: 'quality' | 'smoke', enabled: boolean) => {
    if (!enabled) return
    setExpanded(current => (current === key ? null : key))
  }

  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
        {qualityTag && (
          <Tag
            data-testid="report-trust-quality"
            color={qualityTag.color}
            style={{ cursor: qualityWarnings.length ? 'pointer' : 'default', marginInlineEnd: 0 }}
            onClick={() => toggle('quality', qualityWarnings.length > 0)}
          >
            {qualityTag.label}
          </Tag>
        )}
        {smokeTag && (
          <Tooltip title={smokeTag.tooltip || undefined}>
            <Tag
              data-testid="report-trust-smoke"
              color={smokeTag.color}
              style={{ cursor: smokeChecks.length ? 'pointer' : 'default', marginInlineEnd: 0 }}
              onClick={() => toggle('smoke', smokeChecks.length > 0)}
            >
              {smokeTag.label}
            </Tag>
          </Tooltip>
        )}
        {visualTag && (
          <Tag data-testid="report-trust-visual" color={visualTag.color} style={{ marginInlineEnd: 0 }}>
            {visualTag.label}
          </Tag>
        )}
        {factsTag && (
          <Tag data-testid="report-trust-facts" color={factsTag.color} style={{ marginInlineEnd: 0 }}>
            {factsTag.label}
          </Tag>
        )}
        {normalizationTag && (
          <Tooltip title={normalizationTag.tooltip || undefined}>
            <Tag data-testid="report-trust-normalization" color={normalizationTag.color} style={{ marginInlineEnd: 0 }}>
              {normalizationTag.label}
            </Tag>
          </Tooltip>
        )}
      </div>
      {expanded === 'quality' && qualityWarnings.length > 0 && (
        <ul data-testid="report-trust-quality-detail" style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12, color: '#667085' }}>
          {qualityWarnings.map((warning, index) => (
            <li key={`${warning.code || 'warning'}-${index}`}>
              {warning.code ? <code style={{ fontSize: 11 }}>{warning.code}</code> : null}
              {warning.code && warning.message ? ' — ' : ''}
              {warning.message || ''}
              {warning.severity === 'fail' ? ' (blocking)' : ''}
            </li>
          ))}
        </ul>
      )}
      {expanded === 'smoke' && smokeChecks.length > 0 && (
        <ul data-testid="report-trust-smoke-detail" style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12, color: '#667085' }}>
          {smokeChecks.map((check, index) => (
            <li key={`${check.check || 'check'}-${index}`}>
              {check.check ? <code style={{ fontSize: 11 }}>{check.check}</code> : null}
              {check.check && check.detail ? ' — ' : ''}
              {check.detail || ''}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function qualityTagProps(quality?: QualityResult): { label: string; color: string } | null {
  if (!quality?.status) return null
  const version = quality.rubric_version ? ` (v${quality.rubric_version})` : ''
  const warningCount = quality.warnings?.length || 0
  if (quality.status === 'pass') return { label: `Quality pass${version}`, color: 'success' }
  if (quality.status === 'warn') {
    return { label: `Quality: ${warningCount || 'some'} warning${warningCount === 1 ? '' : 's'}${version}`, color: 'gold' }
  }
  if (quality.status === 'fail') return { label: `Quality failed${version}`, color: 'error' }
  if (quality.status === 'off') return { label: 'Quality gate off', color: 'default' }
  return null
}

function smokeTagProps(smoke?: RuntimeSmoke): { label: string; color: string; tooltip?: string } | null {
  if (!smoke?.status) return null
  if (smoke.status === 'passed') return { label: 'Browser checks passed', color: 'success' }
  if (smoke.status === 'failed') {
    const count = smoke.checks?.length || 0
    return { label: `Browser checks failed${count ? ` (${count})` : ''}`, color: 'error' }
  }
  if (smoke.status === 'skipped') {
    // Never let a skipped browser check read as a pass.
    return { label: 'Browser checks skipped', color: 'gold', tooltip: smoke.reason || 'No browser evidence for this run.' }
  }
  return null
}

function visualTagProps(review?: VisualReviewSummary): { label: string; color: string } | null {
  if (!review) return null
  if (review.status === 'approved') {
    return { label: `Visual review approved${review.reviewer ? ` · ${review.reviewer}` : ''}`, color: 'success' }
  }
  if (review.required) {
    return { label: 'Visual review required — not approved', color: 'gold' }
  }
  return null
}

function factsTagProps(facts?: FactVerification): { label: string; color: string } | null {
  if (!facts?.status) return null
  const bound = facts.bound_fact_count ?? facts.binding_count
  if (facts.status === 'pass') {
    return { label: `Facts verified${typeof bound === 'number' ? ` · ${bound} bound` : ''}`, color: 'success' }
  }
  return { label: `Fact verification failed (${facts.findings?.length || 0})`, color: 'error' }
}

function normalizationTagProps(normalization?: NormalizationSummary): { label: string; color: string; tooltip?: string } | null {
  if (!normalization?.mode) return null
  if (normalization.authoring_tier === 'verified_freeform') {
    return { label: 'Verified freeform', color: 'purple', tooltip: 'Authored page preserved; displayed facts verified against the contract.' }
  }
  if (normalization.mode === 'preserved_low_confidence') {
    return {
      label: 'Preserved · low confidence',
      color: 'volcano',
      tooltip: 'Source extraction was unreliable. Not publishable without a fact contract.',
    }
  }
  if (normalization.mode === 'typed_preservation') return { label: 'Typed preservation', color: 'blue' }
  if (normalization.mode === 'structured_rebuild') return { label: 'Structured rebuild', color: 'default' }
  return null
}
