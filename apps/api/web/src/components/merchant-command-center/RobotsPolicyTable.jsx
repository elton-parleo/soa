import React from 'react'
import { ROBOTS_STATE } from './verificationModel.js'
import { text } from './ComparisonTable.jsx'

const STATE_TONE = {
  [ROBOTS_STATE.ALLOWED]: 'sync',
  [ROBOTS_STATE.BLOCKED]: 'fail',
  [ROBOTS_STATE.PARTIAL]: 'drift',
  [ROBOTS_STATE.UNKNOWN]: 'hold',
}

const STATE_LABEL = {
  [ROBOTS_STATE.ALLOWED]: 'allowed',
  [ROBOTS_STATE.BLOCKED]: 'blocked',
  [ROBOTS_STATE.PARTIAL]: 'partial',
  [ROBOTS_STATE.UNKNOWN]: 'unknown',
}

/**
 * What a surface's domain tells the six named AI agents.
 *
 * An independent question from every other outcome on the row, and
 * often the one that explains the rest of it: a surface can serve us a
 * perfect page and still be closed to every agent a shopper would
 * actually use. Rendered as its own compact sub-table per domain rather
 * than folded into the outcome badge, because it is a different fact
 * about a different party.
 *
 * `unknown` is rendered as unknown. robots.txt that could not be read is
 * never a guess in either direction.
 */
export default function RobotsPolicyTable({ policy }) {
  if (!policy) return null

  return (
    <div className="mcc-robots">
      <div className="mcc-robots-head">
        <span className="mcc-robots-title">Agent access · <span className="mono">{text(policy.domain)}</span></span>
        {!policy.readable && (
          <span className="mcc-badge hold">robots.txt unreadable — no policy known</span>
        )}
        {policy.readable && policy.closedToAllAgents && (
          <span className="mcc-badge fail">
            Closed to all {policy.agentCount} agents
          </span>
        )}
        {policy.readable && !policy.closedToAllAgents && policy.blockedCount > 0 && (
          <span className="mcc-badge drift">
            {policy.blockedCount} of {policy.agentCount} agents blocked
          </span>
        )}
        {policy.readable && policy.blockedCount === 0 && policy.agentCount > 0 && (
          <span className="mcc-badge sync">Open to all {policy.agentCount} agents</span>
        )}
      </div>

      {policy.agents.length > 0 && (
        <table className="mcc-robots-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Platform</th>
              <th>Role</th>
              <th>Site root</th>
              <th>Product pages</th>
              <th>Rule</th>
            </tr>
          </thead>
          <tbody>
            {policy.agents.map((agent) => (
              <tr key={agent.agent || Math.random()}>
                <td className="mono">{text(agent.agent)}</td>
                <td>{text(agent.platform)}</td>
                <td className="mcc-robots-role">{text(agent.role)}</td>
                <td><span className={`mcc-robots-state tone-${STATE_TONE[agent.root]}`}>{STATE_LABEL[agent.root]}</span></td>
                <td><span className={`mcc-robots-state tone-${STATE_TONE[agent.productPages]}`}>{STATE_LABEL[agent.productPages]}</span></td>
                <td className="mono mcc-robots-rule">{text(agent.rule, '—')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Where a named agent's group differs from the `*` default —
          the domain singled that agent out on purpose. */}
      {policy.divergence.length > 0 && (
        <ul className="mcc-robots-divergence">
          {policy.divergence.map((note, i) => (
            <li key={i}>{text(note)}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
