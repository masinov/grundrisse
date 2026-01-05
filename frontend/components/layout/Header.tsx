'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import SearchInput from '@/components/search/SearchInput';

export default function Header() {
  const pathname = usePathname();

  const navLinks = [
    { href: '/authors', label: 'Authors' },
    { href: '/about', label: 'About' },
  ];

  return (
    <header className="border-b border-gray-200 bg-white">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2">
            <span className="text-2xl font-bold text-primary-600">Grundrisse</span>
          </Link>

          {/* Navigation */}
          <nav className="hidden md:flex items-center gap-6">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={`text-sm font-medium transition-colors ${
                  pathname === link.href
                    ? 'text-primary-600'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                {link.label}
              </Link>
            ))}
          </nav>

          {/* Search */}
          <div className="w-64">
            <SearchInput />
          </div>
        </div>
      </div>
    </header>
  );
}
