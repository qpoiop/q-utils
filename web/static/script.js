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
	const previewDoc = previewFrame.contentDocument || previewFrame.contentWindow.document;
	previewDoc.open();
	previewDoc.write(html);
	previewDoc.close();
  }
  
  const debouncedPreview = debounce(updatePreview, 300);
  
  function convertHTML() {
	const htmlContent = document.getElementById("htmlInput").value;
	if (!htmlContent.trim()) {
	  alert("HTML 내용을 입력하세요.");
	  return;
	}
  
	fetch("/convert", {
	  method: "POST",
	  headers: { "Content-Type": "application/json" },
	  body: JSON.stringify({ html: htmlContent }),
	})
	  .then((response) => response.blob())
	  .then((blob) => {
		const url = window.URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = "output.pdf";
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
	  });
  }
  
  function convertURL() {
	const urlInput = document.getElementById("urlInput").value;
	if (!urlInput.trim()) {
	  alert("URL을 입력하세요.");
	  return;
	}
  
	fetch("/convert_url", {
	  method: "POST",
	  headers: { "Content-Type": "application/json" },
	  body: JSON.stringify({ url: urlInput }),
	})
	  .then((response) => response.blob())
	  .then((blob) => {
		const url = window.URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = "webpage.pdf";
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
	  });
  }
  
  // 이벤트 등록
  document.addEventListener("DOMContentLoaded", () => {
	const htmlInput = document.getElementById("htmlInput");
	if (htmlInput) {
	  htmlInput.addEventListener("input", debouncedPreview);
	}
  });
  