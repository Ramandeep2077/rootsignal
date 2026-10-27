import type { Metadata } from "next";
import { DemoBanner } from "@/components/demo-banner";
import { Nav } from "@/components/nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "RootSignal",
  description: "AI incident response copilot: grouped incidents, root-cause analysis and human-approved remediation.",
};

// Runs before first paint: apply a saved theme choice so there's no light/dark flash.
const themeScript = `(function(){try{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}})()`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-screen antialiased">
        <Nav />
        <DemoBanner />
        <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{children}</main>
      </body>
    </html>
  );
}
