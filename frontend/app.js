/**
 * Behavioral Intelligence Tool — Frontend
 * Handles form submission, SSE streaming, card rendering, drawer, and verdict calculation.
 * Includes confidence badges (verified/inferred) and interpretation support.
 */

const DIMENSION_ORDER = [
    'director_track_record',
    'control_network',
    'filing_discipline',
    'governance_stability',
    'ownership_clarity',
    'transaction_readiness',
];

const DIMENSION_META = {
    director_track_record: { icon: '\uD83D\uDC65', title: 'Director Track Record' },
    control_network:       { icon: '\uD83D\uDD17', title: 'Connected Parties' },
    filing_discipline:     { icon: '\uD83D\uDCCB', title: 'Filing Discipline' },
    governance_stability:  { icon: '\uD83D\uDEE1\uFE0F', title: 'Governance Stability' },
    ownership_clarity:     { icon: '\uD83C\uDFDB\uFE0F', title: 'Ownership Clarity' },
    transaction_readiness: { icon: '\uD83D\uDCCA', title: 'Closing Friction' },
};

const BADGE_LABELS = {
    clean: '\u2713 Clean',
    investigate: '\u26A0 Investigate',
    red_flag: '\uD83D\uDEA9 Red Flag',
};

const CONFIDENCE_LABELS = {
    verified: '\u2713 VERIFIED',
    inferred: '\u26A1 INFERRED',
    partial: '\u2139 PARTIAL',
};

// Default interpretation content (fallback if not provided by backend)
const DEFAULT_INTERPRETATIONS = {
    director_track_record: {
        why_matters: [
            'Past insolvencies may indicate governance issues or value extraction patterns',
            'Serial director metrics reveal professional track record across companies'
        ],
        innocent_explanations: [
            'External market factors or industry downturns beyond director control',
            'Unlucky timing or legitimate business pivots'
        ],
        what_we_checked: ['Director appointments, insolvency records, disqualifications, dissolution rates']
    },
    control_network: {
        why_matters: [
            'Concentrated decision-making can indicate related party risk',
            'Recent changes may signal ownership restructuring ahead of transactions'
        ],
        innocent_explanations: [
            'Efficient family business or founder-led structure',
            'Planned succession or legitimate group reorganization'
        ],
        what_we_checked: ['Director overlaps, PSC records, appointment timing']
    },
    filing_discipline: {
        why_matters: [
            'Late filings often correlate with weak finance function or cash constraints',
            'Amendments may indicate error-prone accounting processes'
        ],
        innocent_explanations: [
            'One-off adviser failure or staff turnover',
            'System migration causing timing issues'
        ],
        what_we_checked: ['Filing history, deadline calculations, overdue flags']
    },
    governance_stability: {
        why_matters: [
            'High turnover can indicate instability or key person disputes',
            'Timing correlations with filings may suggest governance concerns'
        ],
        innocent_explanations: [
            'Growth-phase restructuring or internationalization',
            'Planned succession executed smoothly'
        ],
        what_we_checked: ['Director tenure, resignation patterns, address changes']
    },
    ownership_clarity: {
        why_matters: [
            'Complex structures may exist for tax or liability reasons worth understanding',
            'Foreign entities require additional verification steps'
        ],
        innocent_explanations: [
            'Legitimate holding structure for group operations',
            'Legacy cleanup in progress'
        ],
        what_we_checked: ['PSC records, ownership chain tracing, corporate layers']
    },
    transaction_readiness: {
        why_matters: [
            'Outstanding charges require lender consent for asset transfers',
            'Multiple creditors may create subordination complexity'
        ],
        innocent_explanations: [
            'Routine refinancing or growth financing',
            'Standard banking relationship with no unusual terms'
        ],
        what_we_checked: ['Charges register, floating charge coverage, creditor identification']
    }
};

// --- State ---
let dimensionData = {};
let companyProfile = null;
let analysisComplete = false;

// --- DOM refs ---
const form = document.getElementById('search-form');
const input = document.getElementById('company-number');
const analyzeBtn = document.getElementById('analyze-btn');
const errorEl = document.getElementById('error-message');
const companyHeader = document.getElementById('company-header');
const companyName = document.getElementById('company-name');
const companyMeta = document.getElementById('company-meta');
const usageIndicator = document.getElementById('usage-indicator');
const lastRefreshed = document.getElementById('last-refreshed');
const grid = document.getElementById('dimensions-grid');
const loadingEl = document.getElementById('loading');
const metadataEl = document.getElementById('metadata');

// Verdict elements
const verdictStrip = document.getElementById('verdict-strip');
const verdictText = document.getElementById('verdict-text');
const verdictDrivers = document.getElementById('verdict-drivers');
const verdictConfidence = document.getElementById('verdict-confidence');
const legendLine = document.getElementById('legend-line');
const microDisclaimer = document.getElementById('micro-disclaimer');

// Popover elements
const methodLimitsBtn = document.getElementById('method-limits-btn');
const methodLimitsPopover = document.getElementById('method-limits-popover');
const popoverClose = document.getElementById('popover-close');

// Drawer elements
const drawerOverlay = document.getElementById('drawer-overlay');
const evidenceDrawer = document.getElementById('evidence-drawer');
const drawerTitle = document.getElementById('drawer-title');
const drawerRating = document.getElementById('drawer-rating');
const drawerEvidenceSummary = document.getElementById('drawer-evidence-summary');
const drawerClose = document.getElementById('drawer-close');
const tabEvidence = document.getElementById('tab-evidence');
const tabInterpretation = document.getElementById('tab-interpretation');
const drawerTabs = document.querySelectorAll('.drawer-tab');

// --- Event listeners ---
form.addEventListener('submit', (e) => {
    e.preventDefault();
    const cn = input.value.trim();
    if (!cn) return;
    runAnalysis(cn);
});

// Popover toggle
methodLimitsBtn?.addEventListener('click', () => {
    methodLimitsPopover.classList.remove('hidden');
});
popoverClose?.addEventListener('click', () => {
    methodLimitsPopover.classList.add('hidden');
});
methodLimitsPopover?.addEventListener('click', (e) => {
    if (e.target === methodLimitsPopover) {
        methodLimitsPopover.classList.add('hidden');
    }
});

// Drawer events
drawerOverlay?.addEventListener('click', closeDrawer);
drawerClose?.addEventListener('click', closeDrawer);
drawerTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        const tabName = tab.dataset.tab;
        switchDrawerTab(tabName);
    });
});

// Close drawer on escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeDrawer();
        methodLimitsPopover?.classList.add('hidden');
    }
});

// --- Main analysis function (uses SSE streaming) ---
async function runAnalysis(companyNumber) {
    // Reset state
    dimensionData = {};
    companyProfile = null;
    analysisComplete = false;

    // Reset UI
    errorEl.classList.add('hidden');
    errorEl.textContent = '';
    companyHeader.classList.add('hidden');
    verdictStrip.classList.add('hidden');
    legendLine.classList.add('hidden');
    microDisclaimer.classList.add('hidden');
    grid.classList.remove('hidden');
    metadataEl.classList.add('hidden');
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = 'Analyzing...';
    closeDrawer();

    // Create skeleton cards
    grid.innerHTML = '';
    DIMENSION_ORDER.forEach(dim => {
        const card = document.createElement('div');
        card.className = 'skeleton-card';
        card.id = `card-${dim}`;
        card.innerHTML = `
            <div class="skeleton-line"></div>
            <div class="skeleton-line"></div>
            <div class="skeleton-line"></div>
            <div style="margin-top: auto; padding-top: 1rem; font-size: 0.75rem; color: var(--text-light);">Analyzing...</div>
        `;
        grid.appendChild(card);
    });

    const startTime = Date.now();

    try {
        const resp = await fetch('/api/analyze/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ company_number: companyNumber }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || `HTTP ${resp.status}`);
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const json = line.slice(6);
                try {
                    const msg = JSON.parse(json);
                    handleSSEMessage(msg);
                } catch (e) {
                    console.warn('SSE parse error:', e);
                }
            }
        }

        // Mark analysis complete
        analysisComplete = true;
        renderVerdictStrip();

        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
        metadataEl.textContent = `Analysis completed in ${elapsed}s`;
        metadataEl.classList.remove('hidden');

    } catch (err) {
        errorEl.textContent = err.message;
        errorEl.classList.remove('hidden');
        grid.classList.add('hidden');
    } finally {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = 'Analyze';
    }
}

function handleSSEMessage(msg) {
    if (msg.type === 'profile') {
        companyProfile = msg.data;
        renderProfile(msg.data);
    } else if (msg.type === 'dimension') {
        dimensionData[msg.data.dimension] = msg.data;
        renderDimension(msg.data);
    } else if (msg.type === 'error') {
        errorEl.textContent = msg.message;
        errorEl.classList.remove('hidden');
    } else if (msg.type === 'complete') {
        analysisComplete = true;
        renderVerdictStrip();
    }
}

function renderProfile(data) {
    companyName.textContent = data.company_name;

    const addr = data.registered_office_address || {};
    const addrStr = [addr.address_line_1, addr.locality, addr.postal_code].filter(Boolean).join(', ');
    const year = data.date_of_creation ? data.date_of_creation.substring(0, 4) : '';
    const status = (data.company_status || '').replace(/-/g, ' ');

    companyMeta.textContent = `Company #${data.company_number} \u2022 Incorporated ${year} \u2022 ${status.charAt(0).toUpperCase() + status.slice(1)}`;
    if (addrStr) companyMeta.textContent += ` \u2022 ${addrStr}`;

    // Usage indicator
    if (data.usage) {
        const runs = data.usage.company_runs || 0;
        if (runs > 0) {
            usageIndicator.textContent = `This company: ${runs} run${runs !== 1 ? 's' : ''}`;
        } else {
            usageIndicator.textContent = '';
        }
    } else {
        usageIndicator.textContent = '';
    }

    // Last refreshed
    lastRefreshed.textContent = `Refreshed: ${new Date().toLocaleTimeString()}`;

    companyHeader.classList.remove('hidden');
}

function renderDimension(data) {
    const dim = data.dimension;
    const existing = document.getElementById(`card-${dim}`);

    const card = document.createElement('div');
    card.className = 'dimension-card';
    card.id = `card-${dim}`;
    card.setAttribute('data-rating', data.rating);
    card.onclick = () => openDrawer(dim);

    const meta = DIMENSION_META[dim] || { icon: '', title: data.title || dim };
    const badgeLabel = BADGE_LABELS[data.rating] || data.rating;

    // Count verified vs inferred evidence
    const evidence = data.evidence || [];
    const verifiedCount = evidence.filter(e => e.confidence === 'verified').length;
    const inferredCount = evidence.filter(e => e.confidence === 'inferred').length;

    // Get interpretation one-liner
    const interp = data.interpretation || DEFAULT_INTERPRETATIONS[dim];
    let interpLine = '';
    if (interp && interp.why_matters && interp.innocent_explanations) {
        interpLine = `Often correlates with ${interp.why_matters[0]?.toLowerCase().replace(/^past insolvencies may indicate /, '').replace(/^late filings often correlate with /, '').replace(/^high turnover can indicate /, '').replace(/^complex structures may exist for /, '').replace(/^outstanding charges require /, '').replace(/^concentrated decision-making can indicate /, '') || 'risk patterns'}, it can also be ${interp.innocent_explanations[0]?.toLowerCase() || 'benign'}.`;
    }

    // Check for inferred evidence
    const hasInferred = inferredCount > 0;

    card.innerHTML = `
        <div class="card-header">
            <div class="card-title-row">
                <span class="card-title">
                    <span class="card-icon">${meta.icon}</span>
                    ${meta.title}
                </span>
                <span class="badge badge-${data.rating}">${badgeLabel}</span>
            </div>
            <div class="card-summary">${escapeHtml(data.summary || '')}</div>
            ${interpLine ? `<div class="card-interpretation">${escapeHtml(interpLine)}</div>` : ''}
            ${hasInferred ? `<div class="card-inferred-indicator">\u26A1 Includes inferred signals</div>` : ''}
            <div class="card-cta">View evidence \u2192</div>
        </div>
    `;

    if (existing) {
        existing.replaceWith(card);
    } else {
        grid.appendChild(card);
    }
}

// --- Verdict calculation ---
function calculateVerdict() {
    const ratings = Object.values(dimensionData).map(d => d.rating);
    const redFlags = ratings.filter(r => r === 'red_flag').length;
    const investigates = ratings.filter(r => r === 'investigate').length;
    const cleans = ratings.filter(r => r === 'clean').length;

    if (redFlags > 0) {
        return { text: 'High watchfulness', class: 'watchful', drivers: `${redFlags} red flag${redFlags > 1 ? 's' : ''}, ${investigates} investigate` };
    } else if (investigates > 0) {
        return { text: 'Proceed but probe', class: 'probe', drivers: `${investigates} investigate, ${cleans} clean` };
    } else {
        return { text: 'Proceed', class: 'proceed', drivers: `${cleans} clean` };
    }
}

function calculateOverallConfidence() {
    let totalEvidence = 0;
    let verifiedEvidence = 0;
    let hasMissingData = false;

    Object.values(dimensionData).forEach(dim => {
        const evidence = dim.evidence || [];
        totalEvidence += evidence.length;
        verifiedEvidence += evidence.filter(e => e.confidence === 'verified').length;
        if (evidence.length === 0 || dim.error) {
            hasMissingData = true;
        }
    });

    const verifiedRatio = totalEvidence > 0 ? verifiedEvidence / totalEvidence : 0;

    if (hasMissingData || verifiedRatio < 0.5) {
        return { level: 'low', label: 'Low' };
    } else if (verifiedRatio < 0.8) {
        return { level: 'medium', label: 'Medium' };
    } else {
        return { level: 'high', label: 'High' };
    }
}

function isLowHistoryCompany() {
    if (!companyProfile || !companyProfile.date_of_creation) return false;
    const created = new Date(companyProfile.date_of_creation);
    const monthsOld = (Date.now() - created.getTime()) / (1000 * 60 * 60 * 24 * 30);
    return monthsOld < 18;
}

function renderVerdictStrip() {
    if (!analysisComplete || Object.keys(dimensionData).length === 0) return;

    const verdict = calculateVerdict();
    const confidence = calculateOverallConfidence();
    const lowHistory = isLowHistoryCompany();

    verdictText.textContent = verdict.text;
    verdictText.className = `verdict-text ${verdict.class}`;

    let driversText = verdict.drivers;
    if (lowHistory) {
        driversText += ' \u2022 Limited history, interpret with caution';
    }
    verdictDrivers.textContent = driversText;

    verdictConfidence.innerHTML = `
        <span class="confidence-dot ${confidence.level}"></span>
        Overall confidence: ${confidence.label}
    `;

    verdictStrip.classList.remove('hidden');
    legendLine.classList.remove('hidden');
    microDisclaimer.classList.remove('hidden');
}

// --- Drawer functions ---
function openDrawer(dimension) {
    const data = dimensionData[dimension];
    if (!data) return;

    const meta = DIMENSION_META[dimension] || { icon: '', title: data.title || dimension };

    // Set header
    drawerTitle.innerHTML = `<span style="margin-right: 0.5rem;">${meta.icon}</span>${meta.title}`;
    drawerRating.textContent = BADGE_LABELS[data.rating] || data.rating;
    drawerRating.className = `badge badge-${data.rating}`;

    // Evidence summary
    const evidence = data.evidence || [];
    const verifiedCount = evidence.filter(e => e.confidence === 'verified').length;
    const inferredCount = evidence.filter(e => e.confidence === 'inferred').length;
    let summaryParts = [];
    if (verifiedCount > 0) summaryParts.push(`${verifiedCount} verified`);
    if (inferredCount > 0) summaryParts.push(`${inferredCount} inferred`);
    drawerEvidenceSummary.textContent = `Evidence: ${evidence.length} items (${summaryParts.join(', ') || 'none'})`;

    // Render evidence tab
    renderEvidenceTab(data);

    // Render interpretation tab
    renderInterpretationTab(dimension, data);

    // Reset to evidence tab
    switchDrawerTab('evidence');

    // Show drawer
    drawerOverlay.classList.add('visible');
    evidenceDrawer.classList.add('visible');
    document.body.style.overflow = 'hidden';
}

function closeDrawer() {
    drawerOverlay.classList.remove('visible');
    evidenceDrawer.classList.remove('visible');
    document.body.style.overflow = '';
}

function switchDrawerTab(tabName) {
    drawerTabs.forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabName);
    });
    tabEvidence.classList.toggle('active', tabName === 'evidence');
    tabInterpretation.classList.toggle('active', tabName === 'interpretation');
}

function renderEvidenceTab(data) {
    const evidence = data.evidence || [];
    const hasInferred = evidence.some(e => e.confidence === 'inferred');

    let html = '';

    // Inferred banner
    if (hasInferred) {
        html += `<div class="inferred-banner">Some findings are inferred patterns, not direct confirmation of underlying events.</div>`;
    }

    // Disclaimer if present
    if (data.disclaimer) {
        html += `<div class="dimension-disclaimer">\u2139\uFE0F ${escapeHtml(data.disclaimer)}</div>`;
    }

    if (evidence.length === 0) {
        html += '<p style="color:var(--text-light);font-size:0.875rem;">No evidence items</p>';
    } else {
        // Group by recency (last 12 months vs older)
        const now = new Date();
        const oneYearAgo = new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000);

        const recent = [];
        const older = [];

        evidence.forEach(e => {
            const dateStr = extractDateFromEvidence(e);
            if (dateStr) {
                const date = new Date(dateStr);
                if (date > oneYearAgo) {
                    recent.push({ ...e, _date: dateStr });
                } else {
                    older.push({ ...e, _date: dateStr });
                }
            } else {
                recent.push({ ...e, _date: null }); // No date, put in recent
            }
        });

        if (recent.length > 0) {
            html += '<div class="evidence-group-header">Recent (Last 12 months)</div>';
            html += recent.map(e => renderDrawerEvidenceItem(e)).join('');
        }

        if (older.length > 0) {
            html += '<div class="evidence-group-header">Older</div>';
            html += older.map(e => renderDrawerEvidenceItem(e)).join('');
        }

        // If no grouping possible (no dates), just render all
        if (recent.length === 0 && older.length === 0) {
            html += evidence.map(e => renderDrawerEvidenceItem(e)).join('');
        }
    }

    // Rating logic
    if (data.rating_logic) {
        html += `<div class="section-label" style="margin-top: 1.5rem;">Rating Logic</div>`;
        html += `<div class="rating-logic">${escapeHtml(data.rating_logic)}</div>`;
    }

    // What to ask
    if (data.what_to_ask && data.what_to_ask.length) {
        html += `<div class="section-label">What to Ask</div>`;
        html += `<ul class="what-to-ask">${data.what_to_ask.map(q => `<li>${escapeHtml(q)}</li>`).join('')}</ul>`;
    }

    tabEvidence.innerHTML = html;
}

function extractDateFromEvidence(e) {
    // Try to find a date in details
    const details = e.details || {};
    const dateKeys = ['date', 'filed_on', 'appointed_on', 'resigned_on', 'created_on', 'notified_on', 'ceased_on', 'due_on'];
    for (const key of dateKeys) {
        if (details[key] && typeof details[key] === 'string' && details[key].match(/^\d{4}-\d{2}-\d{2}/)) {
            return details[key];
        }
    }
    return null;
}

function renderDrawerEvidenceItem(e) {
    const sev = e.severity || 'none';
    const conf = e.confidence || 'verified';
    const confLabel = CONFIDENCE_LABELS[conf] || conf.toUpperCase();
    const dateStr = e._date ? formatDate(e._date) : '';

    // Type label (cleaned up)
    const typeLabel = (e.type || 'evidence').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

    let html = `<div class="drawer-evidence-item severity-${sev}">`;
    html += `<div class="evidence-row">`;
    html += `<span class="evidence-label">${escapeHtml(typeLabel)}</span>`;
    if (dateStr) html += `<span class="evidence-date">${dateStr}</span>`;
    html += `<span class="evidence-confidence ${conf}">${confLabel}</span>`;
    html += `</div>`;
    html += `<div class="evidence-fact">${escapeHtml(e.description || '')}</div>`;

    // Disclaimer for this evidence
    if (e.disclaimer) {
        html += `<div class="evidence-disclaimer">\u2139\uFE0F ${escapeHtml(e.disclaimer)}</div>`;
    }

    // Link
    if (e.link) {
        html += `<a class="evidence-source" href="${escapeHtml(e.link)}" target="_blank" rel="noopener">View on Companies House \u2192</a>`;
    }

    html += `</div>`;
    return html;
}

function formatDate(dateStr) {
    try {
        const date = new Date(dateStr);
        return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
    } catch {
        return dateStr;
    }
}

function renderInterpretationTab(dimension, data) {
    const interp = data.interpretation || DEFAULT_INTERPRETATIONS[dimension] || {};

    let html = '<div class="interpretation-content">';

    if (interp.why_matters && interp.why_matters.length > 0) {
        html += `<div class="interp-section">`;
        html += `<div class="interp-label">Why this matters</div>`;
        html += `<ul>${interp.why_matters.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
        html += `</div>`;
    }

    if (interp.innocent_explanations && interp.innocent_explanations.length > 0) {
        html += `<div class="interp-section">`;
        html += `<div class="interp-label">Common innocent explanations</div>`;
        html += `<ul>${interp.innocent_explanations.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
        html += `</div>`;
    }

    if (interp.what_we_checked && interp.what_we_checked.length > 0) {
        html += `<div class="interp-section">`;
        html += `<div class="interp-label">What we checked</div>`;
        html += `<ul>${interp.what_we_checked.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
        html += `</div>`;
    }

    // Known limitations
    if (data.disclaimer) {
        html += `<div class="interp-section">`;
        html += `<div class="interp-label">Known limitations</div>`;
        html += `<ul><li>${escapeHtml(data.disclaimer)}</li></ul>`;
        html += `</div>`;
    }

    html += '</div>';
    tabInterpretation.innerHTML = html;
}

// Legacy toggle function (no longer needed but kept for safety)
function toggleCard(dim) {
    openDrawer(dim);
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
