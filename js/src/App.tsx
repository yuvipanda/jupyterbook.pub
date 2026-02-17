import { useEffect, useState } from 'react';
import './App.css';
import { LinkGenerator } from './LinkGenerator';
import { getSiteConfig, SiteConfig } from './siteconfig';

export function App() {
  const [siteConfig, setSiteConfig] = useState<SiteConfig | null>(null);

  useEffect(() => {
    (async () => {
      const sc = await getSiteConfig();
      setSiteConfig(sc);
      document.title = sc.site_title;
    })();
  }, []);
  return (
    <>
      <div className='container'>
        <div className='mx-auto col-8'>
          <div className='text-center mt-4'>
            {siteConfig === null ? "Loading..." :
              <>
                <h1>{siteConfig.site_heading}</h1>
                <h5>{siteConfig.site_subheading}</h5>
                <a href='https://github.com/yuvipanda/jupyterbook.pub/issues'>File Issues</a>
              </>
            }
          </div>
          <LinkGenerator />
        </div>
      </div>
    </>
  );
}
