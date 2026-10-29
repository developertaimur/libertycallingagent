import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Liberty Weblab Dialer",
  description: "SignalWire AI cold-calling campaign dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // suppressHydrationWarning: browser extensions (e.g. ColorZilla) inject
    // attributes like cz-shortcut-listen onto <html>/<body> before hydrate.
    <html lang="en" className="dark" suppressHydrationWarning>
      <body
        suppressHydrationWarning
        className="min-h-screen bg-slate-950 font-sans text-slate-100 antialiased"
      >
        <div className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(ellipse_80%_50%_at_50%_-20%,rgba(34,211,238,0.10),transparent_55%),radial-gradient(ellipse_60%_40%_at_90%_10%,rgba(16,185,129,0.06),transparent_50%)]" />
        {children}
      </body>
    </html>
  );
}
