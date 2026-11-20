/*
 * Copyright (c) 2025-2026 Datalayer, Inc.
 * Distributed under the terms of the Modified BSD License.
 */

/**
 * Primer React for the pages of this site, its theme pinned: Datalayer's,
 * following the reader's system colour mode (`auto`), with no chooser. A
 * chooser here would repaint the Primer parts while the Docusaurus page
 * around them stays put.
 *
 * The same file in every Datalayer Docusaurus site; `src/theme/Root` wraps
 * the site in it. `BaseStyles` gives the Primer components their colour-mode
 * attributes and leaves the font, colour and line height to Docusaurus; the
 * primitives give them their CSS variables.
 */

import React, { type ReactNode } from 'react';
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

const INHERIT = { fontFamily: 'inherit', fontSize: 'inherit', lineHeight: 'inherit', color: 'inherit' };

export function PrimerRoot({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider theme={datalayerTheme} colorMode="auto">
      <BaseStyles style={INHERIT}>{children}</BaseStyles>
    </ThemeProvider>
  );
}

export default PrimerRoot;
