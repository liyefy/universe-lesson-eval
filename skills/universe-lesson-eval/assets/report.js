(() => {
  'use strict';
  const seed = JSON.parse(document.getElementById('review-data').textContent);
  let state = JSON.parse(JSON.stringify(seed));
  const key = `universe-eval-review:${seed.audit_id}:${seed.plan_sha256}:${seed.report_sha256}`;
  const status = document.getElementById('save-status');
  const cards = Array.from(document.querySelectorAll('[data-issue]'));
  const allowed = new Set(['unreviewed', 'approve', 'ignore', 'defer']);
  function validate(value) {
    if (!value || value.version !== 1 || value.audit_id !== seed.audit_id || value.plan_sha256 !== seed.plan_sha256 || value.report_sha256 !== seed.report_sha256 || !Array.isArray(value.decisions)) throw new Error('批阅文件不属于当前报告');
    const ids = new Set(seed.decisions.map(row => row.issue_id));
    if (value.decisions.length !== ids.size) throw new Error('批阅项数量不一致');
    for (const row of value.decisions) {
      if (!row || !ids.delete(row.issue_id) || !allowed.has(row.decision) || typeof row.note !== 'string') throw new Error('批阅项缺失、重复或内容无效');
    }
    return value;
  }
  function paint() {
    for (const card of cards) {
      const row = state.decisions.find(item => item.issue_id === card.dataset.issue);
      card.querySelector('select').value = row.decision;
      card.querySelector('textarea').value = row.note;
    }
  }
  function persist() {
    try {
      localStorage.setItem(key, JSON.stringify(state));
      status.textContent = '已暂存到当前浏览器；请导出 JSON 以长期保存或交给后续任务。';
    } catch (error) {
      status.textContent = `浏览器暂存不可用：${error.message}。当前改动仍在页面中，请导出 JSON。`;
    }
  }
  try {
    const stored = localStorage.getItem(key);
    if (stored) {
      state = validate(JSON.parse(stored));
      status.textContent = '已恢复当前报告的浏览器暂存批阅。';
    }
  } catch (error) {
    status.textContent = `未恢复浏览器暂存：${error.message}。可导入已保存的 JSON。`;
  }
  paint();
  for (const card of cards) {
    card.addEventListener('input', () => {
      const row = state.decisions.find(item => item.issue_id === card.dataset.issue);
      row.decision = card.querySelector('select').value;
      row.note = card.querySelector('textarea').value;
      persist();
    });
  }
  document.getElementById('export-decisions').addEventListener('click', () => {
    const blob = new Blob([JSON.stringify(state, null, 2) + '\n'], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'review-decisions.json';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status.textContent = '已发起批阅 JSON 下载；请确认文件已保存。';
  });
  document.getElementById('import-file').addEventListener('change', async event => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      const imported = validate(JSON.parse(await file.text()));
      state = imported;
      paint();
      persist();
    } catch (error) {
      status.textContent = `导入失败：${error.message}。原有批阅已保留。`;
    }
    event.target.value = '';
  });
})();
