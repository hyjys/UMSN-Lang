// UMSN-IDE Web 서비스 워커.
//
// GitHub Pages 같은 정적 호스팅은 응답 헤더를 바꿀 수 없다. 이 서비스 워커가 같은 출처의 응답에
// COOP/COEP 헤더를 붙여 페이지를 cross-origin isolated 로 만든다. 그래야 SharedArrayBuffer 를
// 쓸 수 있고, 실행 중인 프로그램의 엄?(input) 에 콘솔에서 바로 답하고 ■ 멈춰 로 중단할 수 있다.
// 다른 출처(jsDelivr CDN)는 스스로 CORS/CORP 헤더를 주므로 건드리지 않는다.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (new URL(request.url).origin !== self.location.origin) return;
  if (request.cache === "only-if-cached" && request.mode !== "same-origin") return;
  event.respondWith(
    fetch(request).then((response) => {
      if (response.status === 0) return response;
      const headers = new Headers(response.headers);
      headers.set("Cross-Origin-Embedder-Policy", "require-corp");
      headers.set("Cross-Origin-Opener-Policy", "same-origin");
      headers.set("Cross-Origin-Resource-Policy", "same-origin");
      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers,
      });
    })
  );
});
