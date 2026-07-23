/**
 * AI Email Builder assistant for the GrapesJS editor.
 *
 * Mautic's GrapesJsBuilderBundle fires `builder:show` on the `.builder`
 * element (not on document) and passes the live editor instance. We hook
 * into that, capture the editor, and mount a fixed floating "AI 助手" panel
 * on the right side of the screen so it is always visible while editing.
 */
(function () {
  'use strict';

  const PANEL_ID = 'ai-email-builder-floating';
  const MODE_AUTO = 'auto';

  let currentEditor = null;
  let panelBuilt = false;

  function getCsrfToken() {
    return typeof mauticAjaxCsrf !== 'undefined' ? mauticAjaxCsrf : '';
  }

  function getApiUrl(path) {
    const base = typeof mauticBaseUrl !== 'undefined' ? mauticBaseUrl : '/';
    return `${base}s/${path}`.replace(/\/+/g, '/').replace(':/', '://');
  }

  // The Mautic server runs in a sandboxed environment with NO outbound
  // internet, so we cannot call Gemini server-side. Instead we fetch the
  // config (admin-only) and call Gemini directly from the browser, which
  // does have internet via the user's VPN/proxy.
  const SYSTEM_PROMPTS = {
    mjml: 'You are an expert email template developer. Generate a complete, valid MJML email template that matches the user intent. Use only standard MJML tags (mjml, mj-head, mj-body, mj-section, mj-column, mj-text, mj-button, mj-image, mj-divider, mj-spacer). Keep it email-client compatible. Output ONLY the raw MJML XML, no markdown and no code fences.',
    html: 'You are an expert email template developer. Generate a complete, email-client compatible HTML email fragment using table-based layout and inline styles. Output ONLY the raw HTML, no markdown and no code fences.',
  };

  let cachedConfig = null;
  function getConfig() {
    if (cachedConfig) {
      return Promise.resolve(cachedConfig);
    }
    return new Promise((resolve, reject) => {
      mQuery.ajax({
        url: getApiUrl('ai-email-builder/config'),
        type: 'GET',
        dataType: 'json',
      }).done((cfg) => {
        cachedConfig = cfg;
        resolve(cfg);
      }).fail((xhr, textStatus) => {
        reject(new Error('无法读取 AI 配置：' + textStatus));
      });
    });
  }

  function stripCodeFences(text) {
    const m = String(text).trim().match(/^```[a-z]*\s*([\s\S]*?)\s*```$/);
    return m ? m[1].trim() : String(text).trim();
  }

  function callGemini(cfg, prompt, mode) {
    const url = `${cfg.endpoint}${cfg.endpoint.indexOf('?') !== -1 ? '&' : '?'}key=${encodeURIComponent(cfg.apiKey)}`;
    const payload = {
      systemInstruction: { parts: [{ text: SYSTEM_PROMPTS[mode] || SYSTEM_PROMPTS.html }] },
      contents: [{ role: 'user', parts: [{ text: prompt }] }],
      generationConfig: { temperature: 0.2 },
    };
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then((resp) => {
      if (!resp.ok) {
        return resp.text().then((body) => {
          throw new Error('Gemini HTTP ' + resp.status + ': ' + body);
        });
      }
      return resp.json();
    }).then((data) => {
      const text = (data.candidates && data.candidates[0]
        && data.candidates[0].content && data.candidates[0].content.parts
        && data.candidates[0].content.parts[0].text) || '';
      return stripCodeFences(text);
    });
  }

  function detectEditorMode(editor) {
    if (document.querySelector('textarea.builder-mjml')) {
      return 'mjml';
    }
    if (editor && editor.getConfig && editor.getConfig().plugins) {
      const plugins = editor.getConfig().plugins;
      for (let i = 0; i < plugins.length; i += 1) {
        if (typeof plugins[i] === 'function' && plugins[i].name === 'grapesjs-mjml') {
          return 'mjml';
        }
      }
    }
    return 'html';
  }

  function buildPanelHtml() {
    return `
      <div class="ai-panel-header" id="ai-email-builder-header" style="cursor:pointer;display:flex;align-items:center;justify-content:space-between;font-weight:700;font-size:13px;margin-bottom:8px;">
        <span><i class="fa fa-robot"></i> AI 助手</span>
        <span id="ai-email-toggle" style="font-size:16px;line-height:1;">−</span>
      </div>
      <div id="ai-email-body">
        <label for="ai-email-prompt" style="display:block;margin-bottom:6px;font-weight:600;font-size:12px;">输入邮件意图</label>
        <textarea id="ai-email-prompt" rows="4" style="width:100%;box-sizing:border-box;padding:8px;border:1px solid #ccc;border-radius:4px;resize:vertical;font-size:13px;" placeholder="例如：一封促销邮件，主题是夏季大促，包含一张 Banner、一段介绍文字和一个蓝色购买按钮"></textarea>
        <div style="margin-top:8px;">
          <label style="font-size:12px;">生成格式</label>
          <select id="ai-email-mode" style="width:100%;margin-top:4px;padding:6px;border:1px solid #ccc;border-radius:4px;">
            <option value="auto">自动检测</option>
            <option value="mjml">MJML</option>
            <option value="html">HTML</option>
          </select>
        </div>
        <button id="ai-email-generate" type="button" class="btn btn-primary" style="width:100%;margin-top:10px;">
          <i class="fa fa-magic"></i> 生成邮件
        </button>
        <div id="ai-email-preview" style="margin-top:12px;display:none;">
          <label style="font-size:12px;font-weight:600;">生成结果预览</label>
          <pre id="ai-email-preview-code" style="width:100%;max-height:150px;overflow:auto;background:#f5f5f5;border:1px solid #ddd;border-radius:4px;padding:8px;font-size:11px;white-space:pre-wrap;"></pre>
          <button id="ai-email-replace" type="button" class="btn btn-success" style="width:100%;margin-top:6px;">
            <i class="fa fa-check"></i> 替换当前邮件内容
          </button>
        </div>
        <div id="ai-email-error" class="alert alert-danger" style="margin-top:10px;display:none;padding:8px;font-size:12px;"></div>
        <div id="ai-email-loading" style="margin-top:10px;display:none;text-align:center;font-size:12px;">
          <i class="fa fa-spinner fa-spin"></i> 正在生成…
        </div>
      </div>
    `;
  }

  function attachHandlers(panel) {
    const generateBtn = panel.querySelector('#ai-email-generate');
    const replaceBtn = panel.querySelector('#ai-email-replace');
    const promptEl = panel.querySelector('#ai-email-prompt');
    const modeEl = panel.querySelector('#ai-email-mode');
    const previewWrap = panel.querySelector('#ai-email-preview');
    const previewCode = panel.querySelector('#ai-email-preview-code');
    const errorEl = panel.querySelector('#ai-email-error');
    const loadingEl = panel.querySelector('#ai-email-loading');
    const bodyEl = panel.querySelector('#ai-email-body');
    const toggleEl = panel.querySelector('#ai-email-toggle');
    const headerEl = panel.querySelector('#ai-email-builder-header');

    let collapsed = false;
    headerEl.addEventListener('click', () => {
      collapsed = !collapsed;
      bodyEl.style.display = collapsed ? 'none' : 'block';
      toggleEl.textContent = collapsed ? '+' : '−';
    });

    let lastResult = null;

    function showError(message) {
      errorEl.textContent = message;
      errorEl.style.display = 'block';
      previewWrap.style.display = 'none';
      loadingEl.style.display = 'none';
    }

    function clearError() {
      errorEl.textContent = '';
      errorEl.style.display = 'none';
    }

    generateBtn.addEventListener('click', () => {
      if (!currentEditor) {
        showError('编辑器尚未就绪，请稍候或重新打开编辑器。');
        return;
      }
      const prompt = promptEl.value.trim();
      if (!prompt) {
        showError('请输入邮件意图。');
        return;
      }

      const selectedMode = modeEl.value;
      const mode = selectedMode === MODE_AUTO ? detectEditorMode(currentEditor) : selectedMode;

      clearError();
      loadingEl.style.display = 'block';
      previewWrap.style.display = 'none';

      getConfig()
        .then((cfg) => {
          if (!cfg.apiKey) {
            throw new Error('Gemini API key 未配置（请在 config/local.php 设置 gemini_api_key）。');
          }
          return callGemini(cfg, prompt, mode);
        })
        .then((code) => {
          loadingEl.style.display = 'none';
          lastResult = {
            mode,
            mjml: mode === 'mjml' ? code : '',
            html: mode === 'html' ? code : '',
          };
          previewCode.textContent = code;
          previewWrap.style.display = 'block';
        })
        .catch((err) => {
          loadingEl.style.display = 'none';
          showError('生成失败：' + (err && err.message ? err.message : err));
        });
    });

    replaceBtn.addEventListener('click', () => {
      if (!lastResult || !currentEditor) {
        return;
      }
      clearError();

      const code = lastResult.mjml || lastResult.html || '';
      if (!code) {
        showError('没有可替换的内容。');
        return;
      }

      try {
        currentEditor.setComponents(code);
        setTimeout(() => {
          currentEditor.trigger('change');
          if (typeof currentEditor.store === 'function') {
            currentEditor.store();
          }
        }, 100);
      } catch (e) {
        showError('替换内容时出错：' + e.message);
        return;
      }

      replaceBtn.innerHTML = '<i class="fa fa-check"></i> 已替换';
      setTimeout(() => {
        replaceBtn.innerHTML = '<i class="fa fa-check"></i> 替换当前邮件内容';
      }, 1500);
    });
  }

  function ensurePanel() {
    if (panelBuilt) {
      return;
    }
    const existing = document.getElementById(PANEL_ID);
    if (existing) {
      existing.style.display = 'block';
      return;
    }

    const panel = document.createElement('div');
    panel.id = PANEL_ID;
    panel.innerHTML = buildPanelHtml();
    panel.setAttribute('style',
      'position:fixed;top:64px;right:14px;width:330px;z-index:99999;' +
      'background:#fff;border:1px solid #d0d7de;border-radius:10px;' +
      'box-shadow:0 10px 30px rgba(0,0,0,0.18);padding:14px;color:#24292f;' +
      'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;'
    );
    document.body.appendChild(panel);
    attachHandlers(panel);
    panelBuilt = true;
  }

  function hidePanel() {
    const panel = document.getElementById(PANEL_ID);
    if (panel) {
      panel.style.display = 'none';
    }
  }

  function onBuilderShow(event, editor) {
    currentEditor = editor || null;
    if (editor) {
      window.MauticAiEmailEditor = editor;
    }
    ensurePanel();
  }

  function init() {
    // Mautic fires builder:show on the `.builder` element, passing the editor.
    mQuery('.builder').on('builder:show', onBuilderShow);
    mQuery('.builder').on('builder:hide', hidePanel);

    // Fallback: if the builder is launched before this script binds (rare),
    // retry a few times once the builder becomes active.
    let tries = 0;
    const retry = setInterval(() => {
      tries += 1;
      if (currentEditor || tries > 20) {
        clearInterval(retry);
        return;
      }
      if (mQuery('.builder.builder-active').length && window.MauticAiEmailEditor) {
        onBuilderShow(null, window.MauticAiEmailEditor);
        clearInterval(retry);
      }
    }, 500);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
