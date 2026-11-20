/*
 * Copyright (c) 2025-2026 Datalayer, Inc.
 * Distributed under the terms of the Modified BSD License.
 */

/**
 * Docusaurus' root wrapper (swizzled): every page in Primer React's theme,
 * pinned (see `PrimerRoot`).
 */

import React, { type ReactNode } from 'react';
import { PrimerRoot } from './PrimerRoot';

export default function Root({ children }: { children: ReactNode }) {
  return <PrimerRoot>{children}</PrimerRoot>;
}
