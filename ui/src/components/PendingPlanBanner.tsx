import { Button } from 'antd'
import { PauseCircleOutlined } from '@ant-design/icons'
import type { Plan, PlanStep } from '../hooks/usePlans'

type WorkstreamPreview = {
  title: string
  detail: string
  stepCount: number
}

export default function PendingPlanBanner({
  pendingPlans,
  draftPlan,
  open,
  onOpenChange,
  onView,
  onApprove,
  onDeny,
}: {
  pendingPlans: Plan[]
  draftPlan?: Partial<Plan> | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onView: (planId: string) => void
  onApprove: (planId: string) => void
  onDeny: (planId: string) => void
}) {
  const latest = pendingPlans[pendingPlans.length - 1]
  const plan = latest ?? draftPlan ?? null
  if (!plan) return null

  const isDrafting = !latest
  const extra = pendingPlans.length > 1 ? pendingPlans.length - 1 : 0
  const steps = Array.isArray(plan.steps) ? plan.steps : []
  const workstreams = compactWorkstreams(steps)
  const title = plan.name || (isDrafting ? 'Drafting analysis plan...' : 'Untitled plan')

  return (
    <div style={{ maxWidth: 800, margin: '0 auto 8px', position: 'relative' }}>
      {open && (
        <div style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 'calc(100% + 10px)',
          zIndex: 30,
          maxHeight: 'min(62vh, 620px)',
          overflow: 'auto',
          border: '1px solid #ffe08a',
          borderRadius: 10,
          background: '#fffdf5',
          boxShadow: '0 18px 50px rgba(15, 23, 42, 0.18)',
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'space-between',
            padding: '9px 14px', background: '#fff8db', color: '#ad6800',
            borderBottom: '1px solid #ffe08a', fontSize: 13, fontWeight: 800,
          }}>
            <span>{isDrafting ? 'Drafting plan' : 'Needs your review'}</span>
            <button type="button" onClick={() => onOpenChange(false)} style={{
              border: 0, background: 'transparent', color: '#ad6800',
              cursor: 'pointer', fontWeight: 700, padding: 0,
            }}>
              close
            </button>
          </div>

          <div style={{ padding: 18 }}>
            <div style={{
              color: '#98a2b3', fontSize: 12, letterSpacing: 3, fontWeight: 800,
              textTransform: 'uppercase', marginBottom: 6,
            }}>
              Analysis Plan
            </div>
            <h3 style={{ margin: 0, color: '#1f2937', fontSize: 18, lineHeight: 1.25 }}>{title}</h3>
            {plan.description && (
              <p style={{ margin: '8px 0 0', color: '#667085', fontSize: 14, lineHeight: 1.5 }}>
                {plan.description}
              </p>
            )}

            <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 9 }}>
              {workstreams.map((workstream, i) => (
                <CompactWorkstream key={`${workstream.title}-${i}`} workstream={workstream} index={i} />
              ))}
              {isDrafting && workstreams.length < 3 && Array.from({ length: 3 - workstreams.length }).map((_, i) => (
                <SkeletonStep key={i} index={workstreams.length + i} />
              ))}
            </div>
          </div>

          <div style={{
            display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
            padding: '12px 18px', borderTop: '1px solid #eaecf0', background: '#fff',
          }}>
            {latest ? (
              <>
                <Button type="primary" onClick={() => onApprove(latest.id)}>Approve</Button>
                <Button danger onClick={() => onDeny(latest.id)}>Deny</Button>
                <span style={{ color: '#98a2b3', fontSize: 12, fontStyle: 'italic' }}>
                  Type feedback or revision notes in the message box.
                </span>
                <Button style={{ marginLeft: 'auto' }} onClick={() => onView(latest.id)}>Open plan.md</Button>
              </>
            ) : (
              <span style={{ color: '#667085', fontSize: 13 }}>The plan is still being drafted. Details will appear in plan.md when it is submitted.</span>
            )}
          </div>
        </div>
      )}

      <div role="status" aria-live="polite" style={{
        padding: '6px 12px',
        display: 'flex', alignItems: 'center', gap: 8,
        background: '#fffbe6', border: '1px solid #ffe58f', borderRadius: 8, fontSize: 12,
      }}>
        <PauseCircleOutlined style={{ color: '#faad14', fontSize: 14, flexShrink: 0 }} />
        <span style={{ color: '#555', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {isDrafting ? 'Drafting plan' : 'Plan awaiting review'}: <b>{title}</b>{extra > 0 ? ` (+${extra} more)` : ''}
        </span>
        <Button size="small" style={{ marginLeft: 'auto', flexShrink: 0 }} onClick={() => {
          onOpenChange(!open)
          if (latest) onView(latest.id)
        }}>
          {open ? 'Hide plan' : 'Review plan'}
        </Button>
      </div>
    </div>
  )
}

function compactWorkstreams(steps: PlanStep[]): WorkstreamPreview[] {
  if (steps.length <= 3) {
    return steps.map(step => ({
      title: step.name,
      detail: step.description || 'Review the detailed scope in plan.md.',
      stepCount: 1,
    }))
  }

  const groups = [
    {
      title: 'Data readiness',
      pattern: /data|quality|profil|profile|clean|null|range|sanity|schema|source|ingest|validate|grain|coverage/i,
      steps: [] as PlanStep[],
    },
    {
      title: 'Performance analysis',
      pattern: /analysis|performance|player|team|xg|finishing|market|metric|model|predict|feature|leader|style|segment|rank/i,
      steps: [] as PlanStep[],
    },
    {
      title: 'Report package',
      pattern: /report|visual|chart|dashboard|deliver|finding|narrative|artifact|explain|review/i,
      steps: [] as PlanStep[],
    },
    {
      title: 'Execution follow-through',
      pattern: /.*/,
      steps: [] as PlanStep[],
    },
  ]

  steps.forEach(step => {
    const text = `${step.name} ${step.description || ''}`
    const group = groups.find(g => g.pattern.test(text)) || groups[groups.length - 1]
    group.steps.push(step)
  })

  return groups
    .filter(group => group.steps.length > 0)
    .map(group => ({
      title: group.title,
      detail: summarizeStepNames(group.steps),
      stepCount: group.steps.length,
    }))
}

function summarizeStepNames(steps: PlanStep[]) {
  const names = steps.map(step => step.name).filter(Boolean)
  if (names.length === 0) return 'See plan.md for the detailed review plan.'
  if (names.length === 1) return steps[0].description || names[0]
  const summary = names.join('; ')
  return summary.length > 170 ? `${summary.slice(0, 167).trim()}...` : summary
}

function CompactWorkstream({ workstream, index }: { workstream: WorkstreamPreview; index: number }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '26px minmax(0, 1fr)', gap: 10 }}>
      <span style={{
        width: 26, height: 26, borderRadius: '50%', border: '1px solid #d0d5dd',
        display: 'grid', placeItems: 'center', color: '#667085', fontWeight: 700,
        fontSize: 12, background: '#fff',
      }}>
        {index + 1}
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ color: '#2f2f2f', fontWeight: 750, fontSize: 14, lineHeight: 1.3, display: 'flex', gap: 8, alignItems: 'center' }}>
          <span>{workstream.title}</span>
          {workstream.stepCount > 1 && (
            <span style={{ color: '#98a2b3', fontWeight: 700, fontSize: 11 }}>{workstream.stepCount} steps</span>
          )}
        </div>
        <div style={{
          color: '#667085', fontSize: 13, lineHeight: 1.4, marginTop: 2,
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
        }}>
          {workstream.detail}
        </div>
      </div>
    </div>
  )
}

function SkeletonStep({ index }: { index: number }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '26px minmax(0, 1fr)', gap: 10 }}>
      <span style={{
        width: 26, height: 26, borderRadius: '50%', border: '1px solid #d0d5dd',
        display: 'grid', placeItems: 'center', color: '#667085', fontWeight: 700,
        fontSize: 12, background: '#fff',
      }}>
        {index + 1}
      </span>
      <div style={{ paddingTop: 2 }}>
        <div style={{ width: '48%', height: 10, borderRadius: 999, background: '#eef2f6' }} />
        <div style={{ width: '82%', height: 10, borderRadius: 999, background: '#f2f4f7', marginTop: 8 }} />
      </div>
    </div>
  )
}
