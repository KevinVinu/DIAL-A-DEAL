import React, { useState, useEffect } from 'react';
import { NavLink } from '../types';
import { Menu, X, ArrowUpRight, PhoneCall } from 'lucide-react';

interface NavbarProps {
  brandName: string;
  navLinks: NavLink[];
}

export const Navbar: React.FC<NavbarProps> = ({ brandName, navLinks }) => {
  const [scrolled, setScrolled] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 20);
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  // Separate the "Live Voice Demo" link from other nav links
  const tryItLink = navLinks.find((l) => l.href === '#tryit');
  const otherLinks = navLinks.filter((l) => l.href !== '#tryit');

  return (
    <header
      id="main-navbar"
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
        scrolled
          ? 'bg-black/90 backdrop-blur-md border-b border-white/[0.08] py-3.5'
          : 'bg-transparent py-5'
      }`}
    >
      <div className="max-w-7xl mx-auto px-6 sm:px-8 flex items-center justify-between">
        {/* Brand Logo & Name */}
        <a
          href="#"
          className="flex items-center gap-3 group focus:outline-none"
          id="nav-brand-link"
        >
          {/* DIAL-a-DEAL emblem — SachMei clean monochrome styling */}
          <div className="w-8 h-8 rounded-lg bg-white flex items-center justify-center text-black font-bold transition-transform duration-200 group-hover:scale-105">
            <PhoneCall className="w-4 h-4 text-black" />
          </div>

          <div className="flex flex-col">
            <span className="font-heading text-base font-bold tracking-tight text-white group-hover:text-zinc-300 transition-colors">
              {brandName}
            </span>
            <span className="text-[9px] font-mono text-zinc-600 uppercase tracking-widest -mt-0.5">
              Autonomous Sales Agent
            </span>
          </div>
        </a>

        {/* Desktop Nav Links */}
        <nav className="hidden md:flex items-center gap-8 text-xs uppercase tracking-widest font-mono text-zinc-400">
          {otherLinks.map((link) => (
            <a
              key={link.id}
              id={link.id}
              href={link.href}
              className="text-zinc-400 hover:text-white transition-colors duration-150 py-1"
            >
              {link.label}
            </a>
          ))}
        </nav>

        {/* Action Controls (Desktop) */}
        <div className="hidden md:flex items-center gap-3">
          {/* LIVE DEMO — SachMei original emerald highlight button */}
          {tryItLink && (
            <a
              href={tryItLink.href}
              id="nav-tryit-btn"
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-full border border-emerald-500/50 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 hover:border-emerald-400 hover:text-emerald-300 transition-all duration-150 uppercase tracking-wider font-mono"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Live Voice Demo
            </a>
          )}

          {/* Launch / CTA button */}
          <a
            href="#cta"
            id="nav-signup-btn"
            className="inline-flex items-center justify-center px-4 py-2 text-xs font-semibold rounded-full bg-white text-black hover:bg-zinc-200 transition-all duration-150 gap-1.5"
          >
            <span>Deploy Agent</span>
            <ArrowUpRight className="w-3.5 h-3.5" />
          </a>
        </div>

        {/* Mobile Hamburger */}
        <div className="flex md:hidden items-center gap-2">
          <button
            id="mobile-menu-toggle"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="p-2 text-zinc-300 hover:text-white bg-zinc-900 border border-white/10 rounded-lg focus:outline-none"
            aria-label="Toggle menu"
          >
            {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div
          id="mobile-dropdown-nav"
          className="md:hidden mt-3 mx-4 p-5 rounded-2xl bg-zinc-950 border border-white/10 shadow-2xl space-y-4"
        >
          <div className="flex flex-col space-y-3">
            {navLinks.map((link) => (
              <a
                key={link.id}
                href={link.href}
                onClick={() => setMobileMenuOpen(false)}
                className={`text-sm uppercase tracking-wider font-mono py-1 transition-colors ${
                  link.href === '#tryit'
                    ? 'text-emerald-400 hover:text-emerald-300'
                    : 'text-zinc-300 hover:text-white'
                }`}
              >
                {link.href === '#tryit' ? '▶ Live Voice Demo' : link.label}
              </a>
            ))}
          </div>

          <div className="pt-3 border-t border-white/10">
            <a
              href="#cta"
              onClick={() => setMobileMenuOpen(false)}
              className="w-full block text-center py-2.5 px-4 bg-white text-black font-semibold rounded-xl text-xs uppercase tracking-wider"
            >
              Deploy Agent
            </a>
          </div>
        </div>
      )}
    </header>
  );
};
