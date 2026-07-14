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
    <div className="chat-metric">
      <div className="chat-metric__label">
        {data.label}
      </div>
      <div className="chat-metric__value">
        {data.value}
        {data.unit && <span className="chat-metric__unit">{data.unit}</span>}
      </div>
      {data.delta && (
        <div className="chat-metric__delta" style={{ color: TREND_COLOR[trend] }}>
          {TREND_ICON[trend]}
          {data.delta}
        </div>
      )}
    </div>
  )
}
