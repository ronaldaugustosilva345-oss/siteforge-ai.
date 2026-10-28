const $ = (id) => document.getElementById(id);
let theme = 'modern';
for (const button of document.querySelectorAll('.style')) {
  button.addEventListener('click', () => {
    document.querySelectorAll('.style').forEach(b => b.classList.remove('selected'));
    button.classList.add('selected');
    theme = button.dataset.theme;
  });
}
async function checkStatus() {
  try {
    const result = await (await fetch('/api/status')).json();
    const element = $('connection');
    if (result.online && result.available) {
      element.textContent = '● AI configured · ' + result.model;
      element.className = 'status ready';
    } else {
      element.textContent = '● ' + (result.online ? 'Model not installed: ' + result.model : 'AI not configured');
      element.className = 'status offline';
    }
  } catch { $('connection').textContent = '● Backend offline'; $('connection').className = 'status offline'; }
}
function previewDocument(html, css, js) {
  // srcdoc is isolated from the builder origin; no top navigation, same-origin access or popups.
  const cssTag = '<style>' + css.replace(/<\/style/gi, '<\\/style') + '</style>';
  const jsTag = '<script>' + js.replace(/<\/script/gi, '<\\/script') + '</script>';
  let doc = html.replace(/<link\b[^>]*href=["'](?:\.\/)?style\.css["'][^>]*>/gi, '');
  doc = doc.replace(/<script\b[^>]*src=["'](?:\.\/)?script\.js["'][^>]*><\/script>/gi, '');
  doc = doc.replace(/<\/head>/i, cssTag + '</head>');
  doc = doc.replace(/<\/body>/i, jsTag + '</body>');
  return doc;
}
$('generate').addEventListener('click', async () => {
  const description = $('description').value.trim();
  const message = $('message');
  if (description.length < 12) { message.textContent = 'Please write a more detailed description.'; message.className = 'error'; return; }
  $('generate').disabled = true;
  $('generate').firstElementChild.textContent = '✦ Creating your website...';
  message.textContent = 'Generating your website...';
  message.className = '';
  try {
    const access = $('access-code')?.value || '';
    const response = await fetch('/api/generate', { method:'POST', headers:{'Content-Type':'application/json', 'X-SiteForge-Access':access}, body: JSON.stringify({description,theme}) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'An unexpected error occurred.');
    $('empty').style.display = 'none';
    const frame = $('frame');
    frame.style.display = 'block';
    frame.srcdoc = previewDocument(result.html, result.css, result.js);
    $('preview-state').textContent = 'Your website is ready';
    $('download').classList.remove('disabled');
    $('download').dataset.projectId = result.id;
    message.textContent = 'Success! Preview your website and download the ZIP.';
    message.className = 'good';
    refreshPlans();
  } catch (err) { message.textContent = err.message; message.className = 'error'; }
  finally { $('generate').disabled = false; $('generate').firstElementChild.textContent = '✦ Generate website'; }
});
async function refreshPlans() {
  try {
    const r = await fetch('/api/plans');
    const info = await r.json();
    $('quota-label').textContent = `${info.used} of ${info.plans.free.generations} generations used in the last 30 days (on this computer).`;
  } catch { $('quota-label').textContent = 'Usage information unavailable.'; }
}
document.querySelectorAll('.disabled-paid').forEach(button => button.addEventListener('click', () => {
  $('billing-info').textContent = 'Checkout is not enabled yet. Paid plans are displayed for planning only; no payment will be collected.';
  $('billing-info').scrollIntoView({behavior:'smooth', block:'center'});
}));
refreshPlans();
checkStatus();

$('download').addEventListener('click', async (e) => {
  e.preventDefault();
  if (!$('download').dataset.projectId) return;
  try {
    const response = await fetch('/api/download/' + $('download').dataset.projectId,
      {headers:{'X-SiteForge-Access':$('access-code')?.value || ''}});
    if (!response.ok) throw new Error('Download failed; check private test code.');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href=url;link.download='siteforge-website.zip';link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  } catch (err) {$('message').textContent=err.message;$('message').className='error';}
});
