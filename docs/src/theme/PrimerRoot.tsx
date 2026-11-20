/*
 * Copyright (c) 2025-2026 Datalayer, Inc.
 * Distributed under the terms of the Modified BSD License.
 */

/**
 * Primer React for the pages of this site, its theme pinned: Datalayer's,
 * in the colour mode Docusaurus shows, with no chooser of its own. A chooser
 * here would repaint the Primer parts while the Docusaurus page around them
 * stays put.
 *
 * The mode follows the `data-theme` Docusaurus sets on `<html>`, so a site
 * pinned to light stays light on a dark system, and its switch, where it has
 * one, moves Primer with it. `Root` sits above Docusaurus' colour mode
 * provider, so the attribute is read, then watched; the first render, the
 * server's included, starts from the site's `colorMode.defaultMode`.
 *
 * The same file in every Datalayer Docusaurus site; `src/theme/Root` wraps
 * the site in it. `BaseStyles` gives the Primer components their colour-mode
 * attributes and leaves the font, colour and line height to Docusaurus; the
 * primitives give them their CSS variables.
 */

import React, { useEffect, useState, type ReactNode } from 'react';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import { BaseStyles, ThemeProvider } from '@primer/react';
import { datalayerTheme } from '@datalayer/primer-addons/lib/theme/themes/datalayerTheme';

import '@primer/primitives/dist/css/base/size/size.css';
import '@primer/primitives/dist/css/base/typography/typography.css';
import '@primer/primitives/dist/css/base/motion/motion.css';
import '@primer/primitives/dist/css/functional/size/border.css';
import '@primer/primitives/dist/css/functional/size/breakpoints.css';
import '@primer/primitives/dist/css/functional/size/size.css';
import '@primer/primitives/dist/css/functional/size/viewport.css';
import '@primer/primitives/dist/css/functional/themes/light.css';
import '@primer/primitives/dist/css/functional/themes/dark.css';
import '@primer/primitives/dist/css/functional/typography/typography.css';

type PrimerMode = 'day' | 'night';

/** Docusaurus' `light` or `dark` as Primer's `day` or `night`. */
const primerModeOf = (docusaurusMode: string | null | undefined): PrimerMode =>
  docusaurusMode === 'dark' ? 'night' : 'day';

const INHERIT = { fontFamily: 'inherit', fontSize: 'inherit', lineHeight: 'inherit', color: 'inherit' };

export function PrimerRoot({ children }: { children: ReactNode }) {
  const { siteConfig } = useDocusaurusContext();
  const defaultMode = (siteConfig.themeConfig as { colorMode?: { defaultMode?: string } })?.colorMode?.defaultMode;
  const [colorMode, setColorMode] = useState<PrimerMode>(primerModeOf(defaultMode));
  useEffect(() => {
    const html = document.documentElement;
    const follow = () => setColorMode(primerModeOf(html.getAttribute('data-theme')));
    follow();
    const observer = new MutationObserver(follow);
    observer.observe(html, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, []);
  return (
    <ThemeProvider theme={datalayerTheme} colorMode={colorMode}>
      <BaseStyles style={INHERIT}>{children}</BaseStyles>
    </ThemeProvider>
  );
}

export default PrimerRoot;
