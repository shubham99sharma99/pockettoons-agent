import type { Metadata } from "next";
import "./globals.css";
import Nav from "./nav";
import ServerStatus from "./server-status";

export const metadata: Metadata = {
  title: "PocketToons Analytics Agent",
  description: "Ask product questions in plain English; the agent queries the data and shows its evidence.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="top">
          <span className="brand">PocketToons Analytics Agent</span>
          <Nav />
          <ServerStatus />
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
