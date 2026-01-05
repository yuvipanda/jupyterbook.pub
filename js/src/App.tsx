import './App.css';
import { LinkGenerator } from './LinkGenerator';

export function App() {
  return (
    <>
      <div className='container'>
        <div className='mx-auto col-8'>
          <div className='text-center mt-4'>
            <h1>JupyterBook.pub</h1>
            <h4>Instantly build and share your JupyterBook repository from GitHub or Dataverse</h4>
          </div>
          <LinkGenerator />
        </div>
      </div>
    </>
  );
}
