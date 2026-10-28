"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

const NAV = [
  { href: "/", label: "Home" },
  { href: "/holdings", label: "Holdings" },
  { href: "/performance", label: "Performance" },
  { href: "/readiness", label: "Readiness" },
  { href: "/options", label: "Options" },
];

export function SiteNav() {
  const pathname = usePathname();
  const mobileRef = useRef<HTMLDetailsElement>(null);
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  useEffect(() => {
    if (mobileRef.current) mobileRef.current.open = false;
  }, [pathname]);

  return (
    <header className="topbar">
      <Link href="/" className="brand" aria-label="NOVA home">
        <span className="brand-mark">N</span>
        <span>
          <strong>NOVA</strong>
          <small>Trading operations</small>
        </span>
      </Link>
      <nav className="desktop-nav" aria-label="Primary">
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={isActive(item.href) ? "nav-tab active" : "nav-tab"}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="mobile-nav">
        <details ref={mobileRef}>
          <summary>☰ Workspace</summary>
          <div className="mobile-nav-links">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={isActive(item.href) ? "mobile-nav-link active" : "mobile-nav-link"}
                onClick={() => {
                  if (mobileRef.current) mobileRef.current.open = false;
                }}
              >
                {item.label}
              </Link>
            ))}
          </div>
        </details>
      </div>
      <span className="paper-chip">PAPER</span>
    </header>
  );
}
