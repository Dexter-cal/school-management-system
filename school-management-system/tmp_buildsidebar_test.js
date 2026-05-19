const { JSDOM } = require('jsdom');
const fs = require('fs');
const path = require('path');
const html = `<html><body><div id="sidebar"><nav class="sb-nav" id="sb-nav-content"></nav></div><main id="main-content"></main></body></html>`;
const dom = new JSDOM(html, { runScripts: 'dangerously', resources: 'usable' });
const window = dom.window;
const document = window.document;
window.currentUser = { profile: { role: 'superadmin' }, caps: { term_manage: true, ai_tools: true } };
window.navigator = { userAgent: 'node-jsdom' };
const scriptCode = fs.readFileSync(path.join(WindowsPath('c:/Users/n/Desktop/school-management-system-/school-management-system/school/static/school/js/app.js')), 'utf-8');
const scriptEl = document.createElement('script');
scriptEl.textContent = scriptCode;
document.body.appendChild(scriptEl);
if (typeof window.buildSidebar !== 'function') {
  console.error('buildSidebar not defined');
  process.exit(1);
}
try {
  window.buildSidebar();
  const content = document.getElementById('sb-nav-content').innerHTML;
  console.log('buildSidebar succeeded. HTML length:', content.length);
  console.log(content.slice(0, 240));
} catch (e) {
  console.error('buildSidebar threw', e);
  console.error(e.stack);
  process.exit(2);
}
