export interface TransferFile {
  filename: string;
  content: string;
  mime: string;
  summary: string;
}

let releasePrevious: (() => void) | undefined;

/** Called directly from the user's click: awaiting a database first loses native share permission. */
export function offerFile(data: TransferFile): void {
  releasePrevious?.();
  const file = new File([data.content], data.filename, { type: data.mime });
  const url = URL.createObjectURL(file);
  const dialog = document.createElement("dialog");
  dialog.id = "file-transfer-panel";
  dialog.className = "file-transfer stack";
  dialog.setAttribute("aria-label", "导出文件");
  dialog.innerHTML = `<header class="transfer-heading"><h2 class="transfer-name"></h2><button class="transfer-close" type="button" data-transfer="close" aria-label="关闭">×</button></header><p class="transfer-summary"></p><p class="transfer-message" role="status"></p><div class="transfer-actions"><a class="primary" data-transfer="download">下载</a><button class="secondary" type="button" data-transfer="copy">复制</button><button class="secondary" type="button" data-transfer="share">系统分享</button></div><details class="transfer-source"><summary>查看原文</summary><label class="screen-reader" for="transfer-text">完整文件内容</label><textarea id="transfer-text" readonly spellcheck="false"></textarea><button class="secondary small" type="button" data-transfer="select">全选</button></details>`;
  dialog.querySelector(".transfer-name")!.textContent = data.filename;
  dialog.querySelector(".transfer-summary")!.textContent = data.summary;
  const text = dialog.querySelector("textarea")!;
  text.value = data.content;
  const message = dialog.querySelector(".transfer-message")!;
  const say = (value: string) => { message.textContent = value; };
  const link = dialog.querySelector<HTMLAnchorElement>('[data-transfer="download"]')!;
  link.href = url;
  link.download = data.filename;
  link.target = "_blank";
  link.rel = "noopener";
  const shareButton = dialog.querySelector<HTMLButtonElement>('[data-transfer="share"]')!;
  let shareable = false;
  try { shareable = typeof navigator.share === "function" && typeof navigator.canShare === "function" && navigator.canShare({ files: [file] }); } catch { /* Viewer denies sharing. */ }
  shareButton.disabled = !shareable;
  shareButton.hidden = !shareable;
  const source = dialog.querySelector<HTMLDetailsElement>(".transfer-source")!;
  const select = () => { source.open = true; text.focus(); text.select(); text.setSelectionRange(0, text.value.length); };
  const share = () => {
    if (!shareable) return;
    say("请在系统面板完成存储。");
    shareButton.disabled = true;
    try {
      const sharing = navigator.share({ files: [file], title: data.filename });
      if (!sharing || typeof sharing.then !== "function") throw new Error("查看器没有返回系统分享结果。");
      void sharing.then(() => {
        say("已交给系统，请确认文件已存好。");
      }, (error: unknown) => {
        say(error instanceof Error && error.name === "AbortError" ? "分享已取消，可下载或复制。" : "分享未完成，可下载或复制。");
      }).finally(() => { shareButton.disabled = false; });
    } catch { shareButton.disabled = false; say("分享不可用，可下载或复制。"); }
  };
  link.addEventListener("click", () => { say("已请求下载，请确认文件已存好。"); });
  shareButton.addEventListener("click", share);
  dialog.querySelector('[data-transfer="select"]')!.addEventListener("click", select);
  dialog.querySelector('[data-transfer="copy"]')!.addEventListener("click", () => {
    const manual = () => {
      const wasOpen = source.open;
      select();
      try { if (document.execCommand("copy")) { source.open = wasOpen; say("已复制"); return; } } catch { /* Manual selection remains available. */ }
      say("请长按已选文本复制。");
    };
    if (navigator.clipboard?.writeText) void navigator.clipboard.writeText(data.content).then(() => say("已复制"), manual);
    else manual();
  });
  const close = () => { dialog.close(); dialog.remove(); /* Keep the download URL alive until the next export or page unload. */ };
  dialog.querySelector('[data-transfer="close"]')!.addEventListener("click", close);
  document.body.append(dialog);
  dialog.showModal();
  releasePrevious = () => { dialog.remove(); URL.revokeObjectURL(url); };
  if (shareable) share();
  else link.click();
}
