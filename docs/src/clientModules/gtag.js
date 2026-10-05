/*
 * Copyright (c) 2024- Datalayer, Inc.
 *
 * BSD 3-Clause License
 */

const TRACKING_ID = 'G-EYRGHH1GN6';

if (typeof window !== 'undefined') {
  // Docusaurus's Google Analytics route hook calls window.gtag unconditionally.
  // Keep navigation safe when an ad blocker or a Content Security Policy blocks
  // the inline Google bootstrap or the external analytics script.
  window.dataLayer = window.dataLayer || [];
  window.gtag =
    typeof window.gtag === 'function'
      ? window.gtag
      : function gtag() {
          window.dataLayer.push(arguments);
        };

  // The regular Docusaurus bootstrap may already have queued these commands.
  // Only add them when that bootstrap did not run.
  const isConfigured = window.dataLayer.some(
    entry => entry?.[0] === 'config' && entry?.[1] === TRACKING_ID,
  );

  if (!isConfigured) {
    window.gtag('js', new Date());
    window.gtag('config', TRACKING_ID);
  }
}
