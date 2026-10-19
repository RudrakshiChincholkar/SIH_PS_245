import React, { useState, useEffect, useCallback } from 'react';
import './App.css';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

function App() {
  const [activeTab, setActiveTab] = useState('ingest'); // 'ingest' | 'health'

  // Health check state (Part 1)
  const [backendState, setBackendState] = useState({ status: 'loading', data: null, error: null });
  const [dbState, setDbState] = useState({ status: 'loading', data: null, error: null });
  const [healthCheckedAt, setHealthCheckedAt] = useState(null);
  const [isHealthRefreshing, setIsHealthRefreshing] = useState(false);

  // Ingestion states (Part 2)
  const [videoForm, setVideoForm] = useState({
    file: null,
    batch_id: 'BATCH-2026-A1',
    classroom_id: 'ROOM-101',
    recording_date_time: '2026-10-19T09:30',
  });
  const [videoStatus, setVideoStatus] = useState({ loading: false, success: null, error: null });

  const [attendanceFile, setAttendanceFile] = useState(null);
  const [attendanceStatus, setAttendanceStatus] = useState({ loading: false, success: null, errors: null });

  const [scheduleFile, setScheduleFile] = useState(null);
  const [scheduleStatus, setScheduleStatus] = useState({ loading: false, success: null, errors: null });

  // Uploads list
  const [uploads, setUploads] = useState([]);
  const [uploadsLoading, setUploadsLoading] = useState(false);

  // Fetch Health
  const checkHealth = useCallback(async () => {
    setIsHealthRefreshing(true);
    setBackendState((prev) => ({ ...prev, status: 'loading', error: null }));
    setDbState((prev) => ({ ...prev, status: 'loading', error: null }));

    try {
      const res = await fetch(`${API_BASE_URL}/api/health`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setBackendState({ status: 'connected', data, error: null });
    } catch (err) {
      setBackendState({ status: 'disconnected', data: null, error: err.message });
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/health/db`);
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        setDbState({ status: 'connected', data, error: null });
      } else {
        setDbState({ status: 'disconnected', data, error: data.message || `HTTP ${res.status}` });
      }
    } catch (err) {
      setDbState({ status: 'disconnected', data: null, error: err.message });
    }

    setHealthCheckedAt(new Date().toLocaleTimeString());
    setIsHealthRefreshing(false);
  }, []);

  // Fetch Uploads Registry
  const fetchUploads = useCallback(async () => {
    setUploadsLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/ingest/uploads?limit=25`);
      if (res.ok) {
        const data = await res.json();
        setUploads(data.items || []);
      }
    } catch (err) {
      console.error('Failed to load uploads:', err);
    } finally {
      setUploadsLoading(false);
    }
  }, []);

  useEffect(() => {
    checkHealth();
    fetchUploads();
  }, [checkHealth, fetchUploads]);

  // Video Upload Handler
  const handleVideoUpload = async (e) => {
    e.preventDefault();
    if (!videoForm.file) {
      setVideoStatus({ loading: false, success: null, error: 'Please select a video file.' });
      return;
    }
    setVideoStatus({ loading: true, success: null, error: null });

    const formData = new FormData();
    formData.append('file', videoForm.file);
    formData.append('batch_id', videoForm.batch_id);
    formData.append('classroom_id', videoForm.classroom_id);
    formData.append('recording_date_time', videoForm.recording_date_time.replace('T', ' ') + ':00');

    try {
      const res = await fetch(`${API_BASE_URL}/api/ingest/video`, {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();

      if (res.ok) {
        setVideoStatus({
          loading: false,
          success: `Video successfully ingested: ${data.upload.original_filename} (${(data.upload.file_size_bytes / (1024 * 1024)).toFixed(2)} MB)`,
          error: null,
        });
        fetchUploads();
      } else {
        setVideoStatus({
          loading: false,
          success: null,
          error: data.detail || `Upload failed with HTTP ${res.status}`,
        });
      }
    } catch (err) {
      setVideoStatus({ loading: false, success: null, error: err.message || 'Network upload error.' });
    }
  };

  // Attendance CSV Upload Handler
  const handleAttendanceUpload = async (e) => {
    e.preventDefault();
    if (!attendanceFile) {
      setAttendanceStatus({ loading: false, success: null, errors: ['Please select a CSV file.'] });
      return;
    }
    setAttendanceStatus({ loading: true, success: null, errors: null });

    const formData = new FormData();
    formData.append('file', attendanceFile);

    try {
      const res = await fetch(`${API_BASE_URL}/api/ingest/attendance`, {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();

      if (res.ok) {
        setAttendanceStatus({
          loading: false,
          success: data.message || 'Attendance CSV successfully imported.',
          errors: null,
        });
        fetchUploads();
      } else {
        setAttendanceStatus({
          loading: false,
          success: null,
          errors: data.errors || [data.detail || `Import failed with HTTP ${res.status}`],
        });
        fetchUploads(); // refresh so rejected audit appears in table
      }
    } catch (err) {
      setAttendanceStatus({ loading: false, success: null, errors: [err.message || 'Network error'] });
    }
  };

  // Schedule CSV Upload Handler
  const handleScheduleUpload = async (e) => {
    e.preventDefault();
    if (!scheduleFile) {
      setScheduleStatus({ loading: false, success: null, errors: ['Please select a CSV file.'] });
      return;
    }
    setScheduleStatus({ loading: true, success: null, errors: null });

    const formData = new FormData();
    formData.append('file', scheduleFile);

    try {
      const res = await fetch(`${API_BASE_URL}/api/ingest/schedule`, {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();

      if (res.ok) {
        setScheduleStatus({
          loading: false,
          success: data.message || 'Schedule CSV successfully imported.',
          errors: null,
        });
        fetchUploads();
      } else {
        setScheduleStatus({
          loading: false,
          success: null,
          errors: data.errors || [data.detail || `Import failed with HTTP ${res.status}`],
        });
        fetchUploads(); // refresh so rejected audit appears in table
      }
    } catch (err) {
      setScheduleStatus({ loading: false, success: null, errors: [err.message || 'Network error'] });
    }
  };

  return (
    <div className="container">
      <header className="header">
        <span className="badge-tag">SIH 2026 &bull; Problem Statement 245</span>
        <h1 className="title">AI-based Attendance Monitoring System</h1>
        <p className="description">
          Automated attendance verification for skill training centres. Comparing CCTV classroom occupancy estimation with AEBAS biometric attendance records.
        </p>
      </header>

      {/* Navigation Tabs */}
      <nav className="tab-navigation">
        <button
          className={`nav-tab ${activeTab === 'ingest' ? 'active' : ''}`}
          onClick={() => setActiveTab('ingest')}
        >
          Input Ingestion Hub (Part 2)
        </button>
        <button
          className={`nav-tab ${activeTab === 'health' ? 'active' : ''}`}
          onClick={() => setActiveTab('health')}
        >
          System Diagnostics (Part 1)
        </button>
      </nav>

      {/* Tab 1: Ingestion Hub */}
      {activeTab === 'ingest' && (
        <main>
          <div className="ingestion-grid">
            {/* 1. Video Ingestion Card */}
            <div className="card">
              <div className="card-header">
                <h2 className="card-title">1. CCTV Video Ingestion</h2>
                <span className="tag-badge video">Video Stream</span>
              </div>
              <p className="form-help" style={{ marginBottom: '14px' }}>
                Upload recorded CCTV classroom video (.mp4, .avi, .mov &le; 200MB).
              </p>

              <form onSubmit={handleVideoUpload}>
                <div className="form-group">
                  <label className="form-label">Video File</label>
                  <input
                    type="file"
                    accept=".mp4,.avi,.mov"
                    className="form-input"
                    onChange={(e) => setVideoForm({ ...videoForm, file: e.target.files[0] })}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Batch ID</label>
                  <input
                    type="text"
                    className="form-input"
                    value={videoForm.batch_id}
                    onChange={(e) => setVideoForm({ ...videoForm, batch_id: e.target.value })}
                    required
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Classroom / Hall ID</label>
                  <input
                    type="text"
                    className="form-input"
                    value={videoForm.classroom_id}
                    onChange={(e) => setVideoForm({ ...videoForm, classroom_id: e.target.value })}
                    required
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Recording Date &amp; Time (Local IST)</label>
                  <input
                    type="datetime-local"
                    className="form-input"
                    value={videoForm.recording_date_time}
                    onChange={(e) => setVideoForm({ ...videoForm, recording_date_time: e.target.value })}
                    required
                  />
                </div>

                <button type="submit" className="btn-upload" disabled={videoStatus.loading}>
                  {videoStatus.loading ? 'Uploading & Streaming...' : 'Upload Video File'}
                </button>
              </form>

              {videoStatus.success && (
                <div className="feedback-banner success">{videoStatus.success}</div>
              )}
              {videoStatus.error && (
                <div className="feedback-banner error">{videoStatus.error}</div>
              )}
            </div>

            {/* 2. Attendance CSV Ingestion Card */}
            <div className="card">
              <div className="card-header">
                <h2 className="card-title">2. Mock AEBAS Attendance</h2>
                <span className="tag-badge attendance_csv">Attendance CSV</span>
              </div>
              <p className="form-help">
                Upload AEBAS punch records with synthetic candidate identifiers.
              </p>

              <div style={{ marginTop: '10px' }}>
                <a
                  href={`${API_BASE_URL}/api/ingest/templates/attendance`}
                  className="btn-template"
                  download="attendance_template.csv"
                >
                  Download CSV Template
                </a>
              </div>

              <div className="template-box">
                Expected: <code>batch_id,person_ref,punch_in,punch_out</code>
              </div>

              <form onSubmit={handleAttendanceUpload}>
                <div className="form-group">
                  <label className="form-label">Select Attendance CSV</label>
                  <input
                    type="file"
                    accept=".csv,text/csv"
                    className="form-input"
                    onChange={(e) => setAttendanceFile(e.target.files[0])}
                  />
                </div>

                <button type="submit" className="btn-upload" disabled={attendanceStatus.loading}>
                  {attendanceStatus.loading ? 'Validating CSV...' : 'Validate & Import Attendance'}
                </button>
              </form>

              {attendanceStatus.success && (
                <div className="feedback-banner success">{attendanceStatus.success}</div>
              )}
              {attendanceStatus.errors && (
                <div className="feedback-banner error">
                  <strong>Validation Failed (All-or-Nothing Rollback):</strong>
                  <ul className="error-list">
                    {attendanceStatus.errors.map((err, idx) => (
                      <li key={idx}>{err}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {/* 3. Batch Schedule Ingestion Card */}
            <div className="card">
              <div className="card-header">
                <h2 className="card-title">3. Batch Schedule Timetable</h2>
                <span className="tag-badge schedule_csv">Schedule CSV</span>
              </div>
              <p className="form-help">
                Upload skill centre training batches, classroom assignments, and timing.
              </p>

              <div style={{ marginTop: '10px' }}>
                <a
                  href={`${API_BASE_URL}/api/ingest/templates/schedule`}
                  className="btn-template"
                  download="schedule_template.csv"
                >
                  Download CSV Template
                </a>
              </div>

              <div className="template-box">
                Expected: <code>batch_id,classroom_id,class_date,start_time,end_time,enrolled_count</code>
              </div>

              <form onSubmit={handleScheduleUpload}>
                <div className="form-group">
                  <label className="form-label">Select Schedule CSV</label>
                  <input
                    type="file"
                    accept=".csv,text/csv"
                    className="form-input"
                    onChange={(e) => setScheduleFile(e.target.files[0])}
                  />
                </div>

                <button type="submit" className="btn-upload" disabled={scheduleStatus.loading}>
                  {scheduleStatus.loading ? 'Validating CSV...' : 'Validate & Import Schedule'}
                </button>
              </form>

              {scheduleStatus.success && (
                <div className="feedback-banner success">{scheduleStatus.success}</div>
              )}
              {scheduleStatus.errors && (
                <div className="feedback-banner error">
                  <strong>Validation Failed (All-or-Nothing Rollback):</strong>
                  <ul className="error-list">
                    {scheduleStatus.errors.map((err, idx) => (
                      <li key={idx}>{err}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>

          {/* Uploads History Table */}
          <div className="table-card">
            <div className="table-header-row">
              <h2 className="card-title">Upload Registry &amp; Ingestion History</h2>
              <button
                className="btn-secondary"
                onClick={fetchUploads}
                disabled={uploadsLoading}
              >
                {uploadsLoading ? 'Refreshing...' : 'Refresh Uploads'}
              </button>
            </div>

            <div className="table-responsive">
              <table className="custom-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Original Filename</th>
                    <th>Batch / Classroom / Slot</th>
                    <th>Size / Rows</th>
                    <th>Uploaded At</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {uploads.length === 0 ? (
                    <tr>
                      <td colSpan="6" style={{ textAlign: 'center', color: '#64748b', padding: '24px' }}>
                        No uploads recorded yet. Upload a video or CSV above to begin.
                      </td>
                    </tr>
                  ) : (
                    uploads.map((u) => (
                      <tr key={u.id}>
                        <td>
                          <span className={`tag-badge ${u.upload_type}`}>
                            {u.upload_type.replace('_', ' ')}
                          </span>
                        </td>
                        <td>
                          <strong>{u.original_filename}</strong>
                        </td>
                        <td>
                          {u.video_metadata ? (
                            <span>
                              {u.video_metadata.batch_id} &bull; {u.video_metadata.classroom_id}
                            </span>
                          ) : (
                            <span style={{ color: '#94a3b8' }}>&mdash;</span>
                          )}
                        </td>
                        <td>
                          {u.upload_type === 'video'
                            ? `${(u.file_size_bytes / (1024 * 1024)).toFixed(2)} MB`
                            : `${u.row_count} records`}
                        </td>
                        <td>{new Date(u.created_at).toLocaleString()}</td>
                        <td>
                          <span className={`status-pill ${u.status}`}>
                            <span className="status-dot"></span>
                            {u.status}
                          </span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </main>
      )}

      {/* Tab 2: System Health Diagnostics (Part 1) */}
      {activeTab === 'health' && (
        <main>
          <div className="cards-grid">
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
                <div className="feedback-banner error">Error: {backendState.error}</div>
              )}
            </div>

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
                <div className="feedback-banner error">Database Error: {dbState.error}</div>
              )}
            </div>
          </div>

          <div style={{ textAlign: 'center', marginTop: '20px' }}>
            <button
              className="btn-secondary"
              onClick={checkHealth}
              disabled={isHealthRefreshing}
            >
              {isHealthRefreshing ? 'Checking...' : 'Refresh Health Diagnostics'}
            </button>
            {healthCheckedAt && (
              <div style={{ marginTop: '8px', fontSize: '0.82rem', color: '#64748b' }}>
                Last checked at: {healthCheckedAt}
              </div>
            )}
          </div>
        </main>
      )}
    </div>
  );
}

export default App;
