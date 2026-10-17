import { useEffect, useState } from 'react'
import MemTablePanel from './components/MemTablePanel.jsx'
import LevelsPanel from './components/LevelsPanel.jsx'
import EventLog from './components/EventLog.jsx'
import ControlPanel from './components/ControlPanel.jsx'
import { fetchState, resetSimulator, putKey, deleteKey, getKey, scanRange } from './api.js'
import './App.css'

export default function App() {
  const [state, setState] = useState(null)

  async function refresh() {
    setState(await fetchState())
  }

  useEffect(() => {
    refresh()
  }, [])

  async function handlePut(key, value) {
    setState(await putKey(key, value))
  }

  async function handleDelete(key) {
    setState(await deleteKey(key))
  }

  async function handleGet(key) {
    return getKey(key)
  }

  async function handleScan(lo, hi) {
    return scanRange(lo, hi)
  }

  async function handleReset(config) {
    setState(await resetSimulator(config))
  }

  if (!state) {
    return <div className="app">Loading...</div>
  }

  return (
    <div className="app">
      <h1>SEAL-Cache Simulator</h1>
      <div className="layout">
        <div className="column">
          <ControlPanel
            onPut={handlePut}
            onDelete={handleDelete}
            onGet={handleGet}
            onScan={handleScan}
            onReset={handleReset}
          />
          <MemTablePanel entries={state.memtable} />
        </div>
        <div className="column wide">
          <LevelsPanel levels={state.levels} />
        </div>
        <div className="column">
          <EventLog events={state.events} />
        </div>
      </div>
    </div>
  )
}
