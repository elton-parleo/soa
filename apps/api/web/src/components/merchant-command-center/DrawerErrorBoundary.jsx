import React from 'react'

/**
 * Catches anything the drift inspector throws while rendering and puts
 * a visible panel in its place.
 *
 * The rule it enforces: selecting a row must always produce something
 * on screen. Without a boundary, a render throw unmounts the whole
 * page's subtree and React logs to a console nobody has open — the
 * click just looks dead, which is the single worst failure mode for a
 * control whose only feedback is the panel it opens.
 *
 * `resetKey` is the selected listing+channel. Changing it clears a
 * previous error, so one bad row does not poison every row after it —
 * the operator can click a different listing and carry on.
 */
export default class DrawerErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null, resetKey: props.resetKey }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  static getDerivedStateFromProps(props, state) {
    if (props.resetKey !== state.resetKey) {
      return { error: null, resetKey: props.resetKey }
    }
    return null
  }

  componentDidCatch(error, info) {
    // Still log it — the panel tells the operator, this tells whoever
    // is debugging. Never includes anything but the error itself.
    console.error('[command-center] drift inspector failed to render:', error, info)
  }

  render() {
    if (!this.state.error) return this.props.children

    const message = this.state.error?.message || String(this.state.error)

    return (
      <div className="mcc-drawer-error mcc-panel" role="alert">
        <div className="mcc-drawer-head">
          <h3>Couldn’t render details: {message}</h3>
          {this.props.onClose && (
            <button className="mcc-btn mcc-drawer-close" onClick={this.props.onClose}>
              Close
            </button>
          )}
        </div>
        <div className="mcc-section">
          <p className="mcc-empty">
            The row selected fine — it is this panel that failed, which usually means
            TrueSync returned a record in a shape this page does not know how to draw.
            The matrix above is unaffected; other listings should still open normally.
          </p>
          {this.props.context && (
            <p className="mcc-empty mono" style={{ marginTop: 8 }}>{this.props.context}</p>
          )}
        </div>
      </div>
    )
  }
}
