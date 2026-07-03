/**
 * Attach X-CSRF-Token to same-origin mutating fetch() calls.
 * Token is issued by the server in the XSRF-TOKEN cookie (double-submit pattern).
 */
(function () {
  function readCsrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)XSRF-TOKEN=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  window.getCsrfToken = readCsrfToken;

  var nativeFetch = window.fetch;
  if (!nativeFetch) return;

  window.fetch = function (url, opts) {
    opts = opts || {};
    var method = ((opts.method || "GET") + "").toUpperCase();
    if (method === "GET" || method === "HEAD" || method === "OPTIONS") {
      return nativeFetch(url, opts);
    }
    var token = readCsrfToken();
    if (!token) {
      return nativeFetch(url, opts);
    }
    if (opts.headers instanceof Headers) {
      if (!opts.headers.has("X-CSRF-Token")) {
        opts.headers.set("X-CSRF-Token", token);
      }
    } else {
      opts.headers = opts.headers || {};
      if (!opts.headers["X-CSRF-Token"] && !opts.headers["x-csrf-token"]) {
        opts.headers["X-CSRF-Token"] = token;
      }
    }
    return nativeFetch(url, opts);
  };
})();
