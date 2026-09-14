// debounce 유틸 함수
function debounce(fn, delay) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      fn.apply(this, args);
    }, delay);
  };
}

function updatePreview() {
  const html = document.getElementById("htmlInput").value;
  const previewFrame = document.getElementById("previewFrame");
  const previewDoc =
    previewFrame.contentDocument || previewFrame.contentWindow.document;
  previewDoc.open();
  previewDoc.write(html);
  previewDoc.close();
}

const debouncedPreview = debounce(updatePreview, 300);

// PDF 응답을 받아 다운로드시키는 공통 헬퍼
async function downloadPdf(endpoint, payload, filename) {
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      let message = `요청 실패 (HTTP ${response.status})`;
      try {
        const err = await response.json();
        if (err && err.detail) message = err.detail;
      } catch (_) {
        /* JSON 본문이 없으면 기본 메시지 사용 */
      }
      alert(message);
      return;
    }

    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  } catch (e) {
    alert("네트워크 오류가 발생했습니다.");
    console.error(e);
  }
}

function convertHTML() {
  const htmlContent = document.getElementById("htmlInput").value;
  if (!htmlContent.trim()) {
    alert("HTML 내용을 입력하세요.");
    return;
  }
  downloadPdf("/convert", { html: htmlContent }, "output.pdf");
}

function convertURL() {
  const urlInput = document.getElementById("urlInput").value;
  if (!urlInput.trim()) {
    alert("URL을 입력하세요.");
    return;
  }
  downloadPdf("/convert_url", { url: urlInput }, "webpage.pdf");
}

// ---------------------------------------------------------------------------
// 미디어 추출: SSE 실시간 진행상황
// ---------------------------------------------------------------------------
let mediaSource = null;

function mediaLog(line) {
  const el = document.getElementById("mediaLog");
  el.textContent += line + "\n";
  el.scrollTop = el.scrollHeight;
}

function setProgress(pct) {
  document.getElementById("mediaProgressFill").style.width = (pct || 0) + "%";
}

function startMedia() {
  const url = document.getElementById("mediaUrl").value.trim();
  if (!url) {
    alert("미디어 URL을 입력하세요.");
    return;
  }
  const type = document.querySelector('input[name="mtype"]:checked').value;

  // 이전 스트림 정리 + UI 초기화
  if (mediaSource) mediaSource.close();
  const btn = document.getElementById("mediaStartBtn");
  const dl = document.getElementById("mediaDownload");
  btn.disabled = true;
  dl.style.display = "none";
  document.getElementById("mediaProgressWrap").style.display = "block";
  document.getElementById("mediaLog").textContent = "";
  document.getElementById("mediaStatus").textContent = "시작 중…";
  setProgress(0);

  const qs = `type=${encodeURIComponent(type)}&url=${encodeURIComponent(url)}`;
  mediaSource = new EventSource(`/media/stream?${qs}`);

  mediaSource.onmessage = (e) => {
    const d = JSON.parse(e.data);
    const status = document.getElementById("mediaStatus");

    if (d.phase === "start") {
      status.textContent = `처리 시작 (${d.media_type})`;
    } else if (d.phase === "download") {
      const pct = parseFloat((d.percent || "").replace("%", ""));
      if (!isNaN(pct)) setProgress(pct);
      status.textContent = `다운로드 ${d.percent || ""} ${d.speed || ""} ETA ${d.eta || ""}`.trim();
      if (d.status === "finished") {
        setProgress(100);
        status.textContent = "다운로드 완료 — 변환/병합 중…";
      }
    } else if (d.phase === "postprocess") {
      status.textContent = `후처리: ${d.postprocessor || ""} (${d.status || ""})`;
      mediaLog(`[postprocess] ${d.postprocessor} ${d.status}`);
    } else if (d.phase === "done") {
      setProgress(100);
      status.textContent = "완료 ✅";
      const meta = d.result || {};
      mediaLog(
        `완료: ${meta.resolution || "-"} | ${meta.file_size || "?"} bytes | ${meta.duration || "?"}s`
      );
      const dlEl = document.getElementById("mediaDownload");
      dlEl.href = d.download;
      dlEl.style.display = "inline-block";
      dlEl.textContent = "결과 파일 다운로드";
      document.getElementById("mediaStartBtn").disabled = false;
      mediaSource.close();
    } else if (d.phase === "error") {
      status.textContent = "실패 ❌";
      mediaLog(`오류: ${d.message}`);
      document.getElementById("mediaStartBtn").disabled = false;
      mediaSource.close();
    }
  };

  mediaSource.onerror = () => {
    document.getElementById("mediaStatus").textContent = "연결 오류 (스트림 종료)";
    document.getElementById("mediaStartBtn").disabled = false;
    if (mediaSource) mediaSource.close();
  };
}

// 이벤트 등록
document.addEventListener("DOMContentLoaded", () => {
  const htmlInput = document.getElementById("htmlInput");
  if (htmlInput) {
    htmlInput.addEventListener("input", debouncedPreview);
  }
});
