import { ArrowUpOutlined, ArrowDownOutlined, MinusOutlined } from '@ant-design/icons'

export interface MetricData {
  label: string
  value: string
  delta?: string
  unit?: string
  trend?: 'up' | 'down' | 'flat' | ''
}

const TREND_COLOR = { up: '#52c41a', down: '#ff4d4f', flat: '#8c8c8c', '': '#8c8c8c' }
const TREND_ICON = {
  up: <ArrowUpOutlined />,
  down: <ArrowDownOutlined />,
  flat: <MinusOutlined />,
  '': null,
}

export default function MetricDisplay({ data }: { data: MetricData }) {
  const trend = (data.trend || '') as keyof typeof TREND_COLOR
  return (
    <div style={{
      display: 'inline-flex', flexDirection: 'column', gap: 2,
      background: '#fafafa', border: '1px solid #f0f0f0',
      borderRadius: 8, padding: '12px 16px', minWidth: 140,
    }}>
      <div style={{ fontSize: 11, color: '#8c8c8c', fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
        {data.label}
      </div>
      <div style={{ fontSize: 24, fontWeight: 700, color: '#1a1a1a', lineHeight: 1.2 }}>
        {data.value}
        {data.unit && <span style={{ fontSize: 13, fontWeight: 400, color: '#666', marginLeft: 4 }}>{data.unit}</span>}
      </div>
      {data.delta && (
        <div style={{ fontSize: 12, color: TREND_COLOR[trend], display: 'flex', alignItems: 'center', gap: 3 }}>
          {TREND_ICON[trend]}
          {data.delta}
        </div>
      )}
    </div>
  )
}
