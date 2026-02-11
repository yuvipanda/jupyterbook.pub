import './App.css';
import { LinkGenerator } from './LinkGenerator';

export function App() {
  return (
    <>
      <div className='container'>
        <div className='mx-auto col-8'>
          <div className='text-center mt-4'>
            <h1>JupyterBook.pub</h1>
            <h5>Instantly build and share your JupyterBook repository wherever it is</h5>
            <a href='https://github.com/yuvipanda/jupyterbook.pub/issues'>File Issues</a>
          </div>
          <LinkGenerator />
        </div>
      </div>
    </>
  );
}
