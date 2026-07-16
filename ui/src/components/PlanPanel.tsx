import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Button, Empty, Tag } from 'antd'
import { ArrowsAltOutlined, ExperimentOutlined, ShrinkOutlined } from '@ant-design/icons'
import MarkdownContent from './MarkdownContent'
import type { Plan, PlanStep } from '../hooks/usePlans'

export function PlanStatusTag({ status }: { status?: string }) {
  const colors: Record<string, string> = {
    pending: 'orange', approved: 'blue', running: 'processing', completed: 'green', denied: 'red', changes_requested: 'purple',
  }
  return <Tag color={colors[status || ''] || 'default'} style={{ fontSize: 10 }}>{status}</Tag>
}

function fmtTime(ts?: string): string | null {
  if (!ts) return null
  const ms = Date.parse(ts)
  return isNaN(ms) ? null : new Date(ms).toLocaleString()
}

function statusText(status?: string) {
  return status ? status.replace(/_/g, ' ') : 'not started'
}

function cleanText(text?: string) {
  return (text || '').trim()
}

function isGenericPlanName(name?: string) {
  const cleaned = cleanText(name)
  return !cleaned || /^plan(?:\s+\d+)?$/i.test(cleaned) || /^analysis plan$/i.test(cleaned)
}

function planSortTime(plan: Plan) {
  const parsed = Date.parse(plan.created_at || plan.updated_at || '')
  return Number.isNaN(parsed) ? Number.MAX_SAFE_INTEGER : parsed
}

function planSelectorLabel(plan: Plan, chronologicalIndex: number) {
  const name = cleanText(plan.name)
  return isGenericPlanName(name) ? `Plan ${chronologicalIndex}` : name
}

function outputsMarkdown(outputs?: string[]) {
  const files = outputs?.filter(Boolean) || []
  if (files.length === 0) return ''
  return `\n  - Outputs: ${files.map(p => `\`${p}\``).join(', ')}`
}

function stepLine(step: PlanStep, index: number) {
  const description = cleanText(step.description)
  const summary = cleanText(step.summary)
  const note = cleanText(step.note)
  const parts = [`- **${index + 1}. ${step.name}** (${statusText(step.status)})`]
  if (description) parts.push(`  - Scope: ${description}`)
  if (summary) parts.push(`  - Current note: ${summary}`)
  if (note) parts.push(`  - Caveat: ${note}`)
  const outputs = outputsMarkdown(step.outputs)
  if (outputs) parts.push(outputs)
  return parts.join('\n')
}

function groupStepsForMarkdown(steps: PlanStep[]) {
  if (steps.length === 0) return 'No steps were included in this plan.'
  const groups = [
    {
      title: 'Data readiness and framing',
      pattern: /data|quality|profil|profile|clean|null|range|sanity|schema|source|ingest|validate|grain|coverage/i,
      items: [] as Array<{ step: PlanStep; index: number }>,
    },
    {
      title: 'Analysis workstreams',
      pattern: /analysis|performance|player|team|xg|finishing|market|metric|model|predict|feature|leader|style|segment|rank/i,
      items: [] as Array<{ step: PlanStep; index: number }>,
    },
    {
      title: 'Reporting and review',
      pattern: /report|visual|chart|dashboard|deliver|finding|narrative|artifact|explain|review/i,
      items: [] as Array<{ step: PlanStep; index: number }>,
    },
    {
      title: 'Execution details',
      pattern: /.*/,
      items: [] as Array<{ step: PlanStep; index: number }>,
    },
  ]

  steps.forEach((step, index) => {
    const text = `${step.name} ${step.description || ''}`
    const group = groups.find(g => g.pattern.test(text)) || groups[groups.length - 1]
    group.items.push({ step, index })
  })

  return groups
    .filter(group => group.items.length > 0)
    .map(group => `### ${group.title}\n\n${group.items.map(({ step, index }) => stepLine(step, index)).join('\n\n')}`)
    .join('\n\n')
}

function buildPlanMarkdown(plan: Plan, done: number, total: number) {
  const revision = plan.revision != null ? `rev ${plan.revision}` : 'rev 1'
  const updated = fmtTime(plan.updated_at)
  const created = fmtTime(plan.created_at)
  const context = cleanText(plan.context)
  const progress = cleanText(plan.progress_summary)
  const feedback = cleanText(plan.feedback)

  return [
    `# ${plan.name}`,
    cleanText(plan.description) || 'No objective summary was supplied.',
    '## Review Snapshot',
    [
      `- Status: ${statusText(plan.status)}`,
      `- Revision: ${revision}`,
      `- Progress: ${done}/${total} steps completed`,
      created ? `- Created: ${created}` : '',
      updated ? `- Updated: ${updated}` : '',
    ].filter(Boolean).join('\n'),
    '## Current Understanding',
    context || 'No separate context was captured with this plan. The plan should be reviewed against the current chat request and any notebook state visible in the session.',
    '## Proposed Workstreams',
    groupStepsForMarkdown(plan.steps || []),
    '## Validation And QA',
    [
      '- Confirm dataset scope, row counts, key fields, and grain before interpreting metrics.',
      '- Check nulls, ranges, duplicates, categorical coverage, and suspicious synthetic or anomalous patterns.',
      '- Record assumptions and caveats in the notebook and final `explain.md` before presenting conclusions.',
      '- Tie each chart or metric back to a reproducible notebook cell and durable output path.',
    ].join('\n'),
    '## Expected Deliverables',
    [
      '- A notebook with executed cells, visible validation checks, and final summary.',
      '- Durable outputs for any tables, charts, model diagnostics, or report assets created by the plan.',
      '- A concise App/report surface plus `explain.md` as the written companion.',
    ].join('\n'),
    '## Risks And Open Questions',
    [
      '- Confirm whether the requested analysis is exploratory, explanatory, predictive, or reporting-first before over-optimizing the workflow.',
      '- Flag data quality issues that could change rankings, correlations, or model conclusions.',
      '- Ask for retargeting before execution if the user wants a narrower entity, cohort, or decision angle.',
    ].join('\n'),
    progress ? `## Latest Progress\n\n${progress}` : '',
    feedback ? `## Requested Changes\n\n> ${feedback.replace(/\n/g, '\n> ')}` : '',
  ].filter(Boolean).join('\n\n')
}

function normalizePlanMarkdown(plan: Plan, done: number, total: number) {
  const raw = cleanText(plan.plan_markdown)
  if (!raw) return buildPlanMarkdown(plan, done, total)
  if (/^#\s+/m.test(raw.slice(0, 160))) return raw
  return [`# ${plan.name}`, cleanText(plan.description), raw].filter(Boolean).join('\n\n')
}

export default function PlanPanel({
  plans,
  focusedPlan,
  onFileClick,
  onViewExperiments,
  expanded,
  onExpandedChange,
}: {
  plans: Plan[]
  // A fresh object per focus request — object identity re-triggers the effect
  focusedPlan?: { id: string } | null
  onFileClick?: (path: string) => void
  onViewExperiments?: () => void
  expanded?: boolean
  onExpandedChange?: (expanded: boolean) => void
}) {
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null)
  const [showList, setShowList] = useState(true)
  const containerRef = useRef<HTMLDivElement>(null)

  const defaultPlanId = useMemo(() => {
    const pending = [...plans].reverse().find(p => p.status === 'pending')
    if (pending) return pending.id
    const running = [...plans].reverse().find(p => p.status === 'running' || p.status === 'approved')
    if (running) return running.id
    return plans[plans.length - 1]?.id ?? null
  }, [plans])

  const chronologicalPlanNumbers = useMemo(() => {
    const sorted = [...plans].sort((a, b) => {
      const timeDelta = planSortTime(a) - planSortTime(b)
      if (timeDelta !== 0) return timeDelta
      return (a.iteration || 0) - (b.iteration || 0)
    })
    return new Map(sorted.map((item, index) => [item.id, index + 1]))
  }, [plans])

  useEffect(() => {
    if (plans.length === 0) {
      setSelectedPlanId(null)
      return
    }
    setSelectedPlanId(current => plans.some(p => p.id === current) ? current : defaultPlanId)
  }, [plans, defaultPlanId])

  // Focus requests from the chat card / banner ("View plan →")
  useEffect(() => {
    if (!focusedPlan) return
    setSelectedPlanId(focusedPlan.id)
    setShowList(false)
    // Let the selected plan render before scrolling; no .focus() calls —
    // keyboard focus stays where the user left it.
    const t = setTimeout(() => {
      containerRef.current?.querySelector(`[data-plan-id="${focusedPlan.id}"]`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 100)
    return () => clearTimeout(t)
  }, [focusedPlan])

  if (plans.length === 0) {
    return <Empty description="No plans yet" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 24 }} />
  }

  const plan = plans.find(p => p.id === selectedPlanId) ?? plans.find(p => p.id === defaultPlanId) ?? plans[0]
  const total = plan.steps?.length || 0
  const done = plan.steps?.filter(s => s.status === 'completed').length || 0
  const planDocument = normalizePlanMarkdown(plan, done, total)
  const sortedPlans = [...plans].sort((a, b) => {
    const rank = (item: Plan) => item.status === 'pending' ? 0 : item.status === 'running' || item.status === 'approved' ? 1 : 2
    const rankDelta = rank(a) - rank(b)
    if (rankDelta !== 0) return rankDelta
    return planSortTime(b) - planSortTime(a)
  })

  if (showList) {
    return (
      <div ref={containerRef} style={{ display: 'grid', gap: 8 }}>
        {sortedPlans.map((item, index) => {
          const itemTotal = item.steps?.length || 0
          const itemDone = item.steps?.filter(step => step.status === 'completed').length || 0
          const progress = itemTotal ? Math.round((itemDone / itemTotal) * 100) : 0
          return (
            <button key={item.id} type="button" data-plan-id={item.id} onClick={() => { setSelectedPlanId(item.id); setShowList(false) }} style={{ width: '100%', border: '1px solid #dfe5ec', borderRadius: 8, padding: 12, color: '#344054', background: '#fff', cursor: 'pointer', textAlign: 'left' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 7 }}>
                <strong title={planSelectorLabel(item, chronologicalPlanNumbers.get(item.id) || index + 1)} style={{ flex: '1 1 auto', minWidth: 0, display: '-webkit-box', overflow: 'hidden', WebkitBoxOrient: 'vertical', WebkitLineClamp: 2, fontSize: 13, lineHeight: 1.35 }}>{planSelectorLabel(item, chronologicalPlanNumbers.get(item.id) || index + 1)}</strong>
                <span style={{ flex: '0 0 auto' }}><PlanStatusTag status={item.status} /></span>
              </div>
              {cleanText(item.description) && <p style={{ margin: '6px 0 8px', color: '#667085', fontSize: 12, lineHeight: 1.4, display: '-webkit-box', overflow: 'hidden', WebkitBoxOrient: 'vertical', WebkitLineClamp: 3 }}>{cleanText(item.description)}</p>}
              <div style={{ height: 4, overflow: 'hidden', borderRadius: 3, background: '#eef1f5' }}><div style={{ width: `${progress}%`, height: '100%', background: '#0b63ce' }} /></div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 6px', marginTop: 7, color: '#667085', fontSize: 10.5 }}>
                <span>{itemDone}/{itemTotal} steps</span><span>·</span><span>rev {item.revision || 1}</span>{fmtTime(item.updated_at) && <><span>·</span><span>{fmtTime(item.updated_at)}</span></>}
              </div>
            </button>
          )
        })}
      </div>
    )
  }

  return (
    <div ref={containerRef} data-plan-id={plan.id} style={{ minWidth: 0, maxWidth: '100%', minHeight: 'calc(100vh - 132px)', overflowX: 'hidden' }}>
      <article style={{
        minWidth: 0,
        maxWidth: '100%',
        color: '#344054',
        fontSize: 13,
        lineHeight: 1.55,
        padding: '2px 2px 32px',
        overflowWrap: 'anywhere',
      }}>
        <Button size="small" type="text" onClick={() => setShowList(true)} style={{ margin: '0 0 8px', paddingInline: 0, color: '#0b63ce', fontSize: 11 }}>
          ← All plans ({plans.length})
        </Button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
          <span style={{
            display: 'inline-flex', alignItems: 'center',
            border: '1px solid #d0d5dd', borderRadius: 6, background: '#fff',
            color: '#667085', padding: '2px 8px', fontSize: 11,
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
          }}>
            plan.md
          </span>
          <PlanStatusTag status={plan.status} />
          {plan.revision != null && plan.revision > 1 && <Tag style={{ fontSize: 10, marginInlineEnd: 0 }}>rev {plan.revision}</Tag>}
          {onExpandedChange && (
            <Button size="small" type="text"
              icon={expanded ? <ShrinkOutlined /> : <ArrowsAltOutlined />}
              onClick={() => onExpandedChange(!expanded)}
              style={{ marginLeft: 'auto', fontSize: 11 }}>
              {expanded ? 'Dock' : 'Expand'}
            </Button>
          )}
        </div>

        <div style={markdownFrameStyle}>
          <MarkdownContent content={planDocument} onFileClick={onFileClick} />
        </div>

        {plan.mlflow_experiment_id && onViewExperiments && (
          <Button size="small" icon={<ExperimentOutlined />}
            style={{ marginTop: 2, fontSize: 11 }} onClick={onViewExperiments}>
            View Experiments
          </Button>
        )}

        {(fmtTime(plan.created_at) || fmtTime(plan.updated_at)) && (
          <div style={{ marginTop: 18, fontSize: 11, color: '#98a2b3' }}>
            {fmtTime(plan.created_at) && <>Created {fmtTime(plan.created_at)}</>}
            {fmtTime(plan.created_at) && fmtTime(plan.updated_at) && ' · '}
            {fmtTime(plan.updated_at) && <>Updated {fmtTime(plan.updated_at)}</>}
          </div>
        )}
      </article>
    </div>
  )
}

const markdownFrameStyle: CSSProperties = {
  color: '#344054',
  fontSize: 13,
  lineHeight: 1.58,
}
