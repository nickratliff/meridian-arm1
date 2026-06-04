require('dotenv').config();
const express = require('express');
const cors = require('cors');
const path = require('path');
const { spawn, execSync } = require('child_process');
const { v4: uuidv4 } = require('uuid');
const fs = require('fs');

// Detect the correct python executable at startup
function detectPython() {
  const candidates = ['python3', 'python3.11', 'python3.12', 'python3.10', 'python'];
  for (const cmd of candidates) {
    try {
      execSync(`${cmd} --version`, { stdio: 'ignore' });
      console.log(`Python executable found: ${cmd}`);
      return cmd;
    } catch {
      // try next
    }
  }
  console.warn('WARNING: No Python executable found. PVA scraper and presentation generator will not work.');
  return 'python3'; // fallback — will fail with a clear error
}

const PYTHON = detectPython();

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Ensure output directories exist
const outputDir = path.join(__dirname, 'output');
const presentationsDir = path.join(outputDir, 'presentations');
if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir);
if (!fs.existsSync(presentationsDir)) fs.mkdirSync(presentationsDir, { recursive: true });

// ─────────────────────────────────────────────
// GET /api/research-stream
// SSE endpoint — streams results from each source as they complete.
// All sources run in parallel. UI updates live.
// Query: ?address=&city=&zip=
// ─────────────────────────────────────────────
app.get('/api/research-stream', async (req, res) => {
  const { address, city = 'Lexington', state = 'KY', zip } = req.query;

  if (!address || !zip) {
    res.status(400).json({ error: 'address and zip are required' });
    return;
  }

  // Set up SSE headers
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no'); // disable nginx buffering on Railway
  res.flushHeaders();

  // Helper: send one SSE event
  const send = (source, status, data = {}) => {
    const payload = JSON.stringify({ source, status, ...data });
    res.write(`data: ${payload}\n\n`);
    if (res.flush) res.flush(); // flush immediately to client
  };

  // Keep-alive ping every 15s so Railway doesn't close the connection
  const ping = setInterval(() => res.write(': ping\n\n'), 15000);

  // ── Run all sources in parallel ──────────────────────────────────────────
  const sources = [

    // PVA — real scraper
    runPythonScript('pva_scraper.py', [address, city, zip])
      .then(data => {
        if (data.error) send('pva', 'error', { message: data.error, data });
        else            send('pva', 'done',  { data });
      })
      .catch(err => send('pva', 'error', { message: err.message })),

    // Remine — pending integration
    Promise.resolve().then(() =>
      send('remine', 'pending', { message: 'Remine integration pending API confirmation' })
    ),

    // AreaPro — pending integration
    Promise.resolve().then(() =>
      send('areapro', 'pending', { message: 'AreaPro integration pending API confirmation' })
    ),

    // Web research — pending build
    Promise.resolve().then(() =>
      send('web', 'pending', { message: 'Web research module pending build' })
    ),

  ];

  // Wait for all to complete, then close the stream
  await Promise.allSettled(sources);
  clearInterval(ping);
  send('done', 'done', { address: `${address}, ${city}, ${state} ${zip}` });
  res.end();
});

// ─────────────────────────────────────────────
// POST /api/generate-presentation
// Generates a .pptx from the PLACE template
// Body: { agentName, agentEmail, agentPhone, agentPhoto,
//         address, city, state, zip, listPrice,
//         sellerName, pvaData, netSheet, motivationData }
// ─────────────────────────────────────────────
app.post('/api/generate-presentation', async (req, res) => {
  const data = req.body;

  if (!data.address || !data.agentName) {
    return res.status(400).json({ error: 'address and agentName are required' });
  }

  const filename = `meridian_${data.address.replace(/\s+/g, '_')}_${Date.now()}.pptx`;
  const outputPath = path.join(presentationsDir, filename);

  try {
    // Pass all data to the Python script as JSON via stdin
    const result = await runPythonScriptWithInput('generate_pptx.py', outputPath, data);

    if (!fs.existsSync(outputPath)) {
      throw new Error('Presentation file was not created');
    }

    res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
    res.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.presentationml.presentation');
    fs.createReadStream(outputPath).pipe(res);

    // Clean up file after sending
    res.on('finish', () => {
      try { fs.unlinkSync(outputPath); } catch (e) { /* ignore */ }
    });

  } catch (err) {
    console.error('Presentation generation error:', err);
    return res.status(500).json({ error: err.message || 'Presentation generation failed' });
  }
});

// ─────────────────────────────────────────────
// POST /api/seller-portal-link
// Generates a unique seller portal token/link
// Body: { sellerName, sellerEmail, address, agentToken }
// ─────────────────────────────────────────────
app.post('/api/seller-portal-link', (req, res) => {
  const { sellerName, sellerEmail, address } = req.body;

  if (!sellerName || !address) {
    return res.status(400).json({ error: 'sellerName and address are required' });
  }

  // Generate unique token — in production this would be stored in a DB
  const token = uuidv4().replace(/-/g, '').substring(0, 10).toUpperCase();
  const portalUrl = `https://meridian.nrrt.com/seller/${token}`;

  // TODO: Store token + listing data in database
  // TODO: Send link to seller via email/text (Brivity CRM integration)

  return res.json({
    success: true,
    token,
    portalUrl,
    message: `Portal link generated for ${sellerName}`
  });
});

// ─────────────────────────────────────────────
// GET /api/agents
// Returns the team agent roster
// ─────────────────────────────────────────────
app.get('/api/agents', (req, res) => {
  // TODO: Pull from database or Brivity CRM
  const agents = [
    {
      id: 'nick',
      name: 'Nick Ratliff',
      email: 'nick@nrrt.com',
      phone: '',
      title: 'Team Lead',
      photo: '/assets/agents/nick.jpg'
    }
    // Add additional agents here
  ];
  res.json({ agents });
});

// ─────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────

function runPythonScript(scriptName, args = []) {
  return new Promise((resolve, reject) => {
    const scriptPath = path.join(__dirname, scriptName);
    const proc = spawn(PYTHON, [scriptPath, ...args], {
      env: { ...process.env }
    });

    let stdout = '';
    let stderr = '';

    // Catch spawn errors (e.g. python3 not found) without crashing Node
    proc.on('error', err => {
      reject(new Error(`Could not start Python: ${err.message}. Ensure python3 is installed on the server.`));
    });

    proc.stdout.on('data', d => stdout += d.toString());
    proc.stderr.on('data', d => stderr += d.toString());

    proc.on('close', code => {
      if (code !== 0) {
        return reject(new Error(`Python script failed (exit ${code}): ${stderr}`));
      }
      try {
        resolve(JSON.parse(stdout));
      } catch {
        resolve({ raw: stdout });
      }
    });
  });
}

function runPythonScriptWithInput(scriptName, outputPath, data) {
  return new Promise((resolve, reject) => {
    const scriptPath = path.join(__dirname, scriptName);
    const proc = spawn(PYTHON, [scriptPath, outputPath], {
      env: { ...process.env }
    });

    let stdout = '';
    let stderr = '';

    // Catch spawn errors without crashing Node
    proc.on('error', err => {
      reject(new Error(`Could not start Python: ${err.message}. Ensure python3 is installed on the server.`));
    });

    proc.stdin.write(JSON.stringify(data));
    proc.stdin.end();

    proc.stdout.on('data', d => stdout += d.toString());
    proc.stderr.on('data', d => stderr += d.toString());

    proc.on('close', code => {
      if (code !== 0) {
        return reject(new Error(`Python script failed (exit ${code}): ${stderr}`));
      }
      resolve(stdout.trim());
    });
  });
}

app.listen(PORT, () => {
  console.log(`Meridian Arm 1 running on http://localhost:${PORT}`);
});
