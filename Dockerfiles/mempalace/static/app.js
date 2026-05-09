// Load version on page load
document.addEventListener('DOMContentLoaded', async () => {
    try {
        const response = await fetch('/version');
        const data = await response.json();
        const versionText = data.version ? `v${data.version}` : 'unknown';
        document.getElementById('footer-version').textContent = versionText;
    } catch (e) {
        document.getElementById('footer-version').textContent = 'v?';
    }
});

// Tab Navigation
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const tabName = btn.getAttribute('data-tab');
        showTab(tabName);
    });
});

function showTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });

    // Show selected tab
    document.getElementById(tabName).classList.add('active');
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');

    // Load data for specific tabs
    if (tabName === 'palace') {
        loadPalaceStatus();
    } else if (tabName === 'status') {
        getPalaceStatus();
        getServiceInfo();
    }
}

// API Helper
async function apiCall(endpoint, method = 'GET', body = null) {
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json',
        }
    };

    if (body) {
        options.body = JSON.stringify(body);
    }

    try {
        const response = await fetch(endpoint, options);
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('API Error:', error);
        return { error: error.message, success: false };
    }
}

// Format Results
function formatResult(result, containerId) {
    const container = document.getElementById(containerId);
    
    if (!result) {
        container.innerHTML = '<div class="result-item error"><p>No response received</p></div>';
        return;
    }

    if (result.error) {
        container.innerHTML = `<div class="result-item error"><p><strong>Error:</strong> ${result.error}</p></div>`;
        return;
    }

    let html = '';

    if (result.success === false) {
        html = `<div class="result-item error">
            <p><strong>Command failed (exit code ${result.returncode})</strong></p>
            ${result.stderr ? `<pre>${escapeHtml(result.stderr)}</pre>` : ''}
            ${result.stdout ? `<pre>${escapeHtml(result.stdout)}</pre>` : ''}
        </div>`;
    } else if (result.success === true) {
        html = `<div class="result-item success">
            <p><strong>✓ Success</strong></p>
            ${result.stdout ? `<pre>${escapeHtml(result.stdout)}</pre>` : ''}
        </div>`;
    } else {
        html = `<div class="result-item"><pre>${escapeHtml(JSON.stringify(result, null, 2))}</pre></div>`;
    }

    container.innerHTML = html;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// SEARCH
async function searchPalace() {
    const query = document.getElementById('query').value.trim();
    if (!query) {
        alert('Enter a search query');
        return;
    }

    document.getElementById('search-results').innerHTML = '<div class="loading">Searching palace...</div>';

    const result = await apiCall(`/search?q=${encodeURIComponent(query)}`);
    formatResult(result, 'search-results');
}

// PALACE STATUS
async function loadPalaceStatus() {
    document.getElementById('palace-status').innerHTML = '<div class="loading">Loading palace structure...</div>';
    
    const result = await apiCall('/status');
    
    let html = '';
    if (result.success) {
        html = `<div class="result-item success">
            <p><strong>Palace Status</strong></p>
            <pre>${escapeHtml(result.stdout)}</pre>
        </div>`;
    } else {
        html = `<div class="result-item warning">
            <p><strong>Palace not yet initialized</strong></p>
            <p>Use the "Mine Data" tab to initialize your palace structure.</p>
            ${result.stdout ? `<pre>${escapeHtml(result.stdout)}</pre>` : ''}
        </div>`;
    }
    
    document.getElementById('palace-status').innerHTML = html;
}

// WAKE-UP CONTEXT
async function getWakeUp() {
    const wing = document.getElementById('wing-filter').value.trim();
    const url = wing ? `/wake-up?wing=${encodeURIComponent(wing)}` : '/wake-up';
    
    document.getElementById('wake-up-context').innerHTML = '<div class="loading">Generating wake-up context...</div>';

    const result = await apiCall(url);
    
    let html = '';
    if (result.success) {
        html = `<div class="result-item success">
            <p><strong>Wake-Up Context${wing ? ' for: ' + wing : ''}</strong></p>
            <pre>${escapeHtml(result.stdout)}</pre>
        </div>`;
    } else {
        html = `<div class="result-item error">
            <p><strong>Failed to generate context</strong></p>
            <pre>${escapeHtml(result.stdout || result.stderr)}</pre>
        </div>`;
    }
    
    document.getElementById('wake-up-context').innerHTML = html;
}

// INIT PALACE
async function initPalace() {
    const dir = document.getElementById('init-dir').value.trim();
    if (!dir) {
        alert('Enter a directory path to scan');
        return;
    }

    document.getElementById('init-result').innerHTML = '<div class="loading">Initializing palace...</div>';

    const result = await apiCall('/init', 'POST', { source_dir: dir });
    formatResult(result, 'init-result');
}

// MINE PALACE
async function minePalace() {
    const dir = document.getElementById('mine-dir').value.trim();
    const mode = document.getElementById('mine-mode').value;
    const wing = document.getElementById('mine-wing').value.trim();

    if (!dir) {
        alert('Enter a directory path to mine');
        return;
    }

    const resultDiv = document.getElementById('mine-result');
    resultDiv.innerHTML = `
        <div class="mine-progress">
            <div class="progress-header">Mining Data...</div>
            <div class="progress-logs"></div>
            <div class="progress-status" style="display: none;"></div>
        </div>
    `;

    try {
        const response = await fetch('/mine', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_dir: dir, mode, wing: wing || undefined })
        });

        if (!response.ok) {
            resultDiv.innerHTML = `<div class="error">Mining failed: ${response.statusText}</div>`;
            return;
        }

        const logsDiv = resultDiv.querySelector('.progress-logs');
        const statusDiv = resultDiv.querySelector('.progress-status');
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        if (data.line) {
                            const logEntry = document.createElement('div');
                            logEntry.className = 'log-line';
                            logEntry.textContent = data.line;
                            logsDiv.appendChild(logEntry);
                            logsDiv.scrollTop = logsDiv.scrollHeight;
                        } else if (data.status === 'complete') {
                            statusDiv.style.display = 'block';
                            if (data.success) {
                                statusDiv.className = 'success';
                                statusDiv.textContent = '✓ Mining completed successfully';
                            } else {
                                statusDiv.className = 'error';
                                statusDiv.textContent = `✗ Mining failed (exit code: ${data.returncode})`;
                            }
                        } else if (data.error) {
                            statusDiv.style.display = 'block';
                            statusDiv.className = 'error';
                            statusDiv.textContent = `✗ Error: ${data.error}`;
                        }
                    } catch (e) {
                        console.error('Failed to parse SSE data:', e);
                    }
                }
            }
        }
    } catch (error) {
        resultDiv.innerHTML = `<div class="error">Mining error: ${error.message}</div>`;
    }
}

// BROWSE FOLDERS
async function browseFolders() {
    const path = document.getElementById('browse-path').value.trim() || '/root';
    const filter = document.getElementById('browse-filter').value.trim();

    document.getElementById('browse-results').innerHTML = '<div class="loading">Loading folders...</div>';

    try {
        const url = `/browse?path=${encodeURIComponent(path)}${filter ? '&filter=' + encodeURIComponent(filter) : ''}`;
        const response = await fetch(url);
        const data = await response.json();

        let html = '';

        if (data.error) {
            html = `<div class="result-item error"><p>${data.error}</p></div>`;
        } else {
            // Show current path and parent navigation
            html = `<div class="result-item">
                <p><strong>Current path:</strong> ${escapeHtml(data.path)}</p>
                ${data.parent ? `<button class="folder-item-btn" onclick="document.getElementById('browse-path').value='${data.parent}'; browseFolders();">↑ Parent</button>` : ''}
            </div>`;

            if (data.items.length === 0) {
                html += '<div class="result-item"><p>No items found</p></div>';
            } else {
                data.items.forEach(item => {
                    const itemClass = item.is_dir ? 'directory' : 'file';
                    html += `<div class="folder-item ${itemClass}">
                        <span class="folder-item-path">${escapeHtml(item.name)}</span>
                        ${item.is_dir ? `
                            <button class="folder-item-btn" onclick="document.getElementById('browse-path').value='${item.path}'; browseFolders();">Open</button>
                            <button class="folder-item-btn" onclick="document.getElementById('mine-dir').value='${item.path}'; document.getElementById('mine-dir').focus();">Use</button>
                        ` : ''}
                    </div>`;
                });
            }
        }

        document.getElementById('browse-results').innerHTML = html;
    } catch (error) {
        document.getElementById('browse-results').innerHTML = `<div class="result-item error"><p>Error: ${error.message}</p></div>`;
    }
}

// PALACE CONTENTS (STATUS TAB)
async function getPalaceStatus() {
    document.getElementById('palace-contents').innerHTML = '<div class="loading">Loading status...</div>';

    const result = await apiCall('/status');
    
    let html = '';
    if (result.success) {
        html = `<div class="result-item success">
            <pre>${escapeHtml(result.stdout)}</pre>
        </div>`;
    } else {
        html = `<div class="result-item warning">
            <p>Palace not initialized yet</p>
            <pre>${escapeHtml(result.stdout)}</pre>
        </div>`;
    }
    
    document.getElementById('palace-contents').innerHTML = html;
}

// SERVICE INFO (STATUS TAB)
async function getServiceInfo() {
    const result = await apiCall('/api/health');
    
    let html = '';
    if (result.status === 'ok') {
        html = `<div class="info-grid">
            <div class="info-item">
                <label>Service Status</label>
                <value style="color: #10b981;">✓ Running</value>
            </div>
            <div class="info-item">
                <label>Palace Directory</label>
                <value>${result.palace_dir}</value>
            </div>
            <div class="info-item">
                <label>Data Exists</label>
                <value>${result.palace_exists ? '✓ Yes' : '✗ No'}</value>
            </div>
            <div class="info-item">
                <label>Service</label>
                <value>${result.service}</value>
            </div>
        </div>`;
    } else {
        html = '<div class="result-item error"><p>Service unavailable</p></div>';
    }
    
    document.getElementById('service-info').innerHTML = html;
}

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    getServiceInfo();
});

// Allow Enter key in search input
document.getElementById('query')?.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        searchPalace();
    }
});

// DELETE PALACE MODAL
function showDeleteConfirmation() {
    const modal = document.getElementById('delete-modal');
    const content = modal.querySelector('.modal-content');
    
    // Reset modal content to original confirmation dialog
    content.innerHTML = `
        <h2>⚠️ Delete All Mined Data</h2>
        <p>This will permanently delete all files in the palace, including:</p>
        <ul>
            <li>Knowledge graph database</li>
            <li>Vector embeddings</li>
            <li>All mined content</li>
        </ul>
        <p><strong>This action cannot be undone.</strong></p>
        <div class="modal-buttons">
            <button onclick="closeDeleteConfirmation()" class="btn-cancel">Cancel</button>
            <button onclick="deletePalaceData()" class="btn-confirm-delete">Yes, Delete Everything</button>
        </div>
    `;
    
    modal.style.display = 'flex';
}

function closeDeleteConfirmation() {
    document.getElementById('delete-modal').style.display = 'none';
}

async function deletePalaceData() {
    try {
        const modal = document.getElementById('delete-modal');
        const content = modal.querySelector('.modal-content');
        const btn = modal.querySelector('.btn-confirm-delete');
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Deleting...';

        const response = await fetch('/delete-palace', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const result = await response.json();

        if (result.success) {
            // Update modal content to show success
            content.innerHTML = `
                <div style="text-align: center; padding: 20px;">
                    <h2 style="color: #10b981; margin-bottom: 10px;">✓ Deletion Complete</h2>
                    <p style="margin-bottom: 20px; color: #888;">All mined data has been successfully deleted.</p>
                    <p style="font-size: 14px; color: #666;">Palace is now ready for fresh data mining.</p>
                </div>
                <div class="modal-buttons">
                    <button onclick="closeDeleteConfirmation(); getPalaceStatus();" class="btn-cancel" style="flex: 1;">Close</button>
                </div>
            `;
        } else {
            // Show error in modal instead of alert
            content.innerHTML = `
                <div style="text-align: center; padding: 20px;">
                    <h2 style="color: #ef4444; margin-bottom: 10px;">✗ Deletion Failed</h2>
                    <p style="margin-bottom: 20px; color: #888;">${result.error}</p>
                </div>
                <div class="modal-buttons">
                    <button onclick="closeDeleteConfirmation();" class="btn-cancel" style="flex: 1;">Close</button>
                </div>
            `;
        }
        getPalaceStatus();
    } catch (error) {
        const modal = document.getElementById('delete-modal');
        const content = modal.querySelector('.modal-content');
        content.innerHTML = `
            <div style="text-align: center; padding: 20px;">
                <h2 style="color: #ef4444; margin-bottom: 10px;">✗ Deletion Failed</h2>
                <p style="margin-bottom: 20px; color: #888;">Network error: ${error.message}</p>
            </div>
            <div class="modal-buttons">
                <button onclick="closeDeleteConfirmation();" class="btn-cancel" style="flex: 1;">Close</button>
            </div>
        `;
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeDeleteConfirmation();
    }
});
