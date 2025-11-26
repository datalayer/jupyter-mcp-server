/*
 * Copyright (c) 2024- Datalayer, Inc.
 *
 * BSD 3-Clause License
 */

import React from 'react';
import clsx from 'clsx';
import styles from './HomepageFeatures.module.css';

const FeatureList = [
/*
  {
    title: 'Easy to Use',
    Svg: require('../../static/img/feature_1.svg').default,
    description: (
      <>
        Datalayer was designed from the ground up to be easily installed and
        used to get your data analysis up and running quickly.
      </>
    ),
  },
  {
    title: 'Focus on What Matters',
    Svg: require('../../static/img/feature_2.svg').default,
    description: (
      <>
        Datalayer lets you focus on your work, and we&apos;ll do the chores.
      </>
    ),
  },
  {
    title: 'Powered by Open Source',
    Svg: require('../../static/img/feature_3.svg').default,
    description: (
      <>
        Extend or customize your platform to your needs.
      </>
    ),
  },
*/
];

function Feature({Svg, title, description}) {
  return (
    <div className={clsx('col col--4')}>
      <div className="text--center">
        <Svg className={styles.featureSvg} alt={title} />
      </div>
      <div className="text--center padding-horiz--md">
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures() {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
