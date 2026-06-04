require('dotenv').config();
const express = require('express');
const cors = require('cors');
const path = require('path');
const { spawn } = require('child_process');
const { v4: uuidv4 } = require('uuid');
const fs = require('fs');

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
// POST /api/research
// Runs PVA scraper + stub data for Remine/AreaPro/web
// Body: { address, city, state, zip }
// ─────────────────────────────────────────────
app.post('/api/research', async (req, res) => {
  const { address, city, state, zip } = req.body;

  if (!address || !zip) {
    return res.status(400).json({ error: 'address and zip are required' });
  }

  try {
    // Run PVA scraper as subprocess
    const pvaData = await runPythonScript('pva_scraper.py', [address, city, zip]);

    // TODO: Add Remine scraper call here when credentials confirmed
    const remineData = { status: 'pending', message: 'Remine integration pending API confirmation' };

    // TODO: Add AreaPro scraper call here when credentials confirmed
    const areaProData = { status: 'pending', message: 'AreaPro integration pending API confirmation' };

    // TODO: Add web research module (neighborhood stats, school ratings, walk score)
    const webResearchData = { status: 'pending', message: 'Web research module pending build' };

    return res.json({
      success: true,
      address: `${address}, ${city}, ${state} ${zip}`,
      pva: pvaData,
      remine: remineData,
      areaPro: areaProData,
      webResearch: webResearchData
    });

  } catch (err) {
    console.error('Research error:', err);
    return res.status(500).json({ error: err.message || 'Research failed' });
  }
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
    const proc = spawn('python3', [scriptPath, ...args], {
      env: { ...process.env }
    });

    let stdout = '';
    let stderr = '';

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
    const proc = spawn('python3', [scriptPath, outputPath], {
      env: { ...process.env }
    });

    let stdout = '';
    let stderr = '';

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
