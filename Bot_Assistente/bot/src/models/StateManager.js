class StateManager {
  constructor() { this._states = {}; }
  getState(phone)             { return this._states[phone] || { state: 'IDLE', data: {} }; }
  setState(phone, state, data = {}) { this._states[phone] = { state, data }; }
  clearState(phone)           { this._states[phone] = { state: 'IDLE', data: {} }; }
}
module.exports = new StateManager();
