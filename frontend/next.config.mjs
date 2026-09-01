/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The gateway base URL is environment configuration, never a literal in code.
  // There is no default: a frontend that silently falls back to some built-in
  // host is a frontend that can point at the wrong bank.
  env: {},
};

export default nextConfig;
