const form = document.querySelector('#download-form');
const submit = document.querySelector('#submit');
const error = document.querySelector('#error');
const quality = document.querySelector('#quality');
let signature = '';

form.addEventListener('change', () => {
  const audio = form.elements.format.value === 'mp3';
  quality.disabled = audio;
  document.querySelector('#format-note').textContent = audio
    ? 'Audio extracted as an MP3 at 192 kbps.'
    : 'Best available MP4 up to your selected resolution.';
});

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function render(jobs) {
  const nextSignature = JSON.stringify(jobs);
  if (nextSignature === signature) return;
  signature = nextSignature;
  document.querySelector('#count').textContent = jobs.length;
  document.querySelector('#empty').hidden = jobs.length > 0;
  const container = document.querySelector('#jobs');
  container.replaceChildren();
  for (const job of jobs) {
    const row = element('article', undefined, 'job');
    row.append(element('div', job.format === 'mp3' ? '♫' : '▻', 'job-icon'));
    const content = element('div', undefined, 'job-content');
    content.append(element('h3', job.title));
    const status = {queued: 'Waiting in queue', downloading: `Downloading · ${Math.round(job.progress)}%`, processing: 'Preparing your file…', ready: 'Ready to download', error: 'Download failed'}[job.status];
    content.append(element('p', `${job.format.toUpperCase()} · ${status}${job.size ? ` · ${(job.size / 1048576).toFixed(1)} MB` : ''}`));
    if (['downloading', 'processing', 'queued'].includes(job.status)) {
      const progress = element('progress');
      progress.max = 100;
      if (job.status === 'downloading') progress.value = job.progress;
      progress.setAttribute('aria-label', 'Download progress');
      content.append(progress);
    }
    if (job.clip) content.append(element('p', `Clip: ${job.clip.start}s–${job.clip.end}s · 5s padding each side, where available`));
    if (job.error) content.append(element('p', job.error, 'failure'));
    row.append(content);
    if (job.status === 'ready') {
      const link = element('a', 'Download ↓', 'download-link');
      link.href = `/files/${encodeURIComponent(job.id)}`;
      link.download = '';
      row.append(link);
    }
    container.append(row);
  }
}

async function refresh() {
  try {
    const response = await fetch('/api/jobs');
    if (response.status === 404) {
      document.querySelector('#connection').textContent = 'Download server not connected';
      const setup = document.querySelector('#setup');
      setup.hidden = false;
      setup.textContent = 'Connect your download server to enable downloads.';
      return;
    }
    if (!response.ok) throw new Error('Could not connect');
    const body = await response.json();
    render(body.jobs);
    document.querySelector('#connection').textContent = '● Server connected';
    const setup = document.querySelector('#setup');
    setup.hidden = !body.missing.length;
    setup.textContent = `Setup needed: ${body.missing.join(', ')}. Start with Docker to install everything automatically.`;
  } catch {
    document.querySelector('#connection').textContent = 'Reconnecting to server…';
  }
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  submit.disabled = true;
  error.hidden = true;
  try {
    const response = await fetch('/api/jobs', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: form.elements.url.value.trim(), format: form.elements.format.value, quality: quality.value, start: form.elements.start.value.trim(), end: form.elements.end.value.trim()})
    });
    if (response.status === 404) throw new Error('The download server is not connected yet.');
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || 'Could not start the download.');
    form.elements.url.value = '';
    await refresh();
  } catch (err) {
    error.textContent = err.message || 'Could not connect to the server.';
    error.hidden = false;
  } finally {
    submit.disabled = false;
  }
});

async function poll() {
  await refresh();
  setTimeout(poll, 2000);
}
poll();
