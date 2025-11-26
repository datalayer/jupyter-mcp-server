/*
 * Copyright (c) 2024- Datalayer, Inc.
 *
 * BSD 3-Clause License
 */

import React from 'react';
import Layout from '@theme/Layout';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import HomepageFeatures from '../components/HomepageFeatures';

export default function Home() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title={`${siteConfig.title}`}
      description="Datalayer, cloud native Jupyter">
      <main>
        <HomepageFeatures />
      </main>
    </Layout>
  );
}
