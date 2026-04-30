"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Search, Users, Briefcase, Settings, Zap, Sun } from "lucide-react";

const navLinks = [
  { href: "/",            label: "Suche",      icon: Search,   group: "business" },
  { href: "/leads",       label: "Leads",      icon: Users,    group: "business" },
  { href: "/auftraege",   label: "Aufträge",   icon: Briefcase,group: "business" },
  { href: "/dach",        label: "Solar-Scan", icon: Sun,      group: "solar" },
  { href: "/dach/leads",  label: "Dach-Leads", icon: Users,    group: "solar" },
  { href: "/einstellungen", label: "Einstellungen", icon: Settings, group: "settings" },
];

export default function Navigation() {
  const pathname = usePathname();

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-50">
      <div className="container mx-auto px-4 max-w-7xl">
        <div className="flex items-center justify-between h-16">
          <Link href="/" className="flex items-center gap-2 font-bold text-xl text-blue-600">
            <Zap className="w-6 h-6" />
            LeadScout
          </Link>

          <nav className="flex items-center gap-1">
            {/* Business-Links */}
            {navLinks.filter((l) => l.group === "business").map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                  pathname === href || (href !== "/" && pathname.startsWith(href))
                    ? "bg-blue-50 text-blue-700"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                )}
              >
                <Icon className="w-4 h-4" />
                {label}
              </Link>
            ))}

            {/* Trenner */}
            <div className="w-px h-5 bg-slate-200 mx-1" />

            {/* Solar-Links */}
            {navLinks.filter((l) => l.group === "solar").map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                  pathname === href || (href !== "/dach" && pathname.startsWith(href))
                    ? "bg-yellow-50 text-yellow-700"
                    : "text-slate-600 hover:bg-yellow-50 hover:text-yellow-700"
                )}
              >
                <Icon className="w-4 h-4" />
                {label}
              </Link>
            ))}

            {/* Trenner */}
            <div className="w-px h-5 bg-slate-200 mx-1" />

            {/* Einstellungen */}
            {navLinks.filter((l) => l.group === "settings").map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                  pathname === href
                    ? "bg-blue-50 text-blue-700"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                )}
              >
                <Icon className="w-4 h-4" />
                {label}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </header>
  );
}
