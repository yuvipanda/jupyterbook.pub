import { LinkGenerator } from "./LinkGenerator";

export function App({
    title,
    heading,
    subheading,
}: {
    title: string;
    heading: string;
    subheading: string;
}) {
    return (
        <>
            <title>{title}</title>
            <div className="container">
                <div className="mx-auto col-8">
                    <div className="text-center mt-4">
                        <h1>{heading}</h1>
                        <h5>{subheading}</h5>
                        <a href="https://github.com/yuvipanda/jupyterbook.pub/issues">
                            File Issues
                        </a>
                    </div>
                    <LinkGenerator />
                </div>
            </div>
        </>
    );
}
