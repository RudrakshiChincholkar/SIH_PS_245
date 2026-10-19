import React, { useState, useEffect, useCallback } from 'react';
import './App.css';

// Read backend API base URL from Vite environment variable
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

function App() {
  const [backendState, setBackendState] = useState({
    status: 'loading', // 'loading' | 'connected' | 'disconnected'
    data: null,
    error: null,
  });

  const [dbState, setDbState] = useState({
    status: 'loading', // 'loading' | 'connected' | 'disconnected'
    data: null,
    error: null,
  });

  const [lastChecked, setLastChecked] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const checkHealth = useCallback(async () => {
    setIsRefreshing(true);
    setBackendState((prev) => ({ ...prev, status: 'loading', error: null }));
    setDbState((prev) => ({ ...prev, status: 'loading', error: null }));

    // 1. Fetch general backend health
    try {
      const response = await fetch(`${API_BASE_URL}/api/health`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });

      if (!response.ok) {
        throw new Error(`Server responded with HTTP ${response.status}`);
      }

      const data = await response.json();
      setBackendState({
        status: 'connected',
        data,
        error: null,
      });
    } catch (err) {
      setBackendState({
        status: 'disconnected',
        data: null,
        error: err.message || 'Network connection failed',
      });
    }

    // 2. Fetch PostgreSQL database health independently
    try {
      const response = await fetch(`${API_BASE_URL}/api/health/db`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });

      const data = await response.json();

      if (response.ok && data.status === 'ok') {
        setDbState({
          status: 'connected',
          data,
          error: null,
        });
      } else {
        setDbState({
          status: 'disconnected',
          data,
          error: data.message || `Database check returned HTTP ${response.status}`,
        });
      }
    } catch (err) {
      setDbState({
        status: 'disconnected',
        data: null,
        error: err.message || 'Database health endpoint unreachable',
      });
    }

    setLastChecked(new Date().toLocaleTimeString());
    setIsRefreshing(false);
  }, []);

  useEffect(() => {
    checkHealth();
  }, [checkHealth]);

  return (
    <div className="container">
      <header className="header">
        <span className="badge-tag">SIH 2026 &bull; Problem Statement 245</span>
        <h1 className="title">AI-based Attendance Monitoring System</h1>
        <p className="description">
          Automated, privacy-preserving verification system comparing CCTV classroom
          occupancy estimation with AEBAS biometric attendance records for
          government-funded skill-development training centres.
        </p>
      </header>

      <main>
        <div className="cards-grid">
          {/* Backend API Health Card */}
          <div className="card">
            <div className="card-header">
              <h2 className="card-title">Backend API Service</h2>
              <span className={`status-pill ${backendState.status}`}>
                <span className="status-dot"></span>
                {backendState.status === 'loading'
                  ? 'Checking...'
                  : backendState.status === 'connected'
                  ? 'Connected'
                  : 'Disconnected'}
              </span>
            </div>

            <div className="details-list">
              <div className="details-row">
                <span className="details-label">API Endpoint</span>
                <span className="details-value">{API_BASE_URL}/api/health</span>
              </div>
              {backendState.data && (
                <>
                  <div className="details-row">
                    <span className="details-label">Service</span>
                    <span className="details-value">{backendState.data.service}</span>
                  </div>
                  <div className="details-row">
                    <span className="details-label">Environment</span>
                    <span className="details-value">{backendState.data.environment}</span>
                  </div>
                  <div className="details-row">
                    <span className="details-label">Version</span>
                    <span className="details-value">{backendState.data.version}</span>
                  </div>
                </>
              )}
            </div>

            {backendState.error && (
              <div className="error-banner">
                <strong>Error:</strong> {backendState.error}
                <div style={{ marginTop: '4px', fontSize: '0.8rem', color: '#7f1d1d' }}>
                  Ensure FastAPI backend is running on <code>{API_BASE_URL}</code>.
                </div>
              </div>
            )}
          </div>

          {/* Database Health Card */}
          <div className="card">
            <div className="card-header">
              <h2 className="card-title">PostgreSQL Database</h2>
              <span className={`status-pill ${dbState.status}`}>
                <span className="status-dot"></span>
                {dbState.status === 'loading'
                  ? 'Checking...'
                  : dbState.status === 'connected'
                  ? 'Connected'
                  : 'Disconnected'}
              </span>
            </div>

            <div className="details-list">
              <div className="details-row">
                <span className="details-label">Health Check</span>
                <span className="details-value">{API_BASE_URL}/api/health/db</span>
              </div>
              {dbState.data && (
                <>
                  <div className="details-row">
                    <span className="details-label">Database Status</span>
                    <span className="details-value">{dbState.data.database}</span>
                  </div>
                  <div className="details-row">
                    <span className="details-label">Message</span>
                    <span className="details-value">{dbState.data.message}</span>
                  </div>
                </>
              )}
            </div>

            {dbState.error && (
              <div className="error-banner">
                <strong>Database Error:</strong> {dbState.error}
                <div style={{ marginTop: '4px', fontSize: '0.8rem', color: '#7f1d1d' }}>
                  Verify PostgreSQL service is active and credentials in backend <code>.env</code> are correct.
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="action-bar">
          <button
            className="refresh-button"
            onClick={checkHealth}
            disabled={isRefreshing}
          >
            {isRefreshing ? 'Checking...' : 'Refresh Status'}
          </button>
          {lastChecked && (
            <span className="last-checked">Last checked at: {lastChecked}</span>
          )}
        </div>

        <div className="info-box">
          <h3 className="info-title">Part 1: Foundation &amp; Environment Setup</h3>
          <p className="info-text">
            This landing page verifies connectivity between the React frontend, FastAPI backend,
            and PostgreSQL database. Subsequent pipeline stages (video ingestion, YOLO person
            counting, AEBAS discrepancy analysis, and the monitoring dashboard) will be added in
            subsequent phases.
          </p>
        </div>
      </main>
    </div>
  );
}

export default App;
