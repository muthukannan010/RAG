const iconPaths = {
  file: (
    <>
      <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
      <path d="M13 2v7h7" />
    </>
  ),

  upload: (
    <>
      <path d="M12 16V4" />
      <path d="m7 9 5-5 5 5" />
      <path d="M4 20h16" />
    </>
  ),

  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),

  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 1.2-2.9 1.7 1.7 0 0 0-1.2-2.9 1.7 1.7 0 0 0-2.9-1.2 1.7 1.7 0 0 0-2.9-1.2 1.7 1.7 0 0 0-3.4 0 1.7 1.7 0 0 0-2.9 1.2 1.7 1.7 0 0 0-2.9 1.2 1.7 1.7 0 0 0 0 3.4 1.7 1.7 0 0 0 1.2 2.9 1.7 1.7 0 0 0 2.9 1.2 1.7 1.7 0 0 0 2.9 1.2 1.7 1.7 0 0 0 3.4 0 1.7 1.7 0 0 0 2.9-1.2 1.7 1.7 0 0 0 1.7-1.7Z" />
    </>
  ),

  send: (
    <>
      <path d="m22 2-7 20-4-9-9-4Z" />
      <path d="M22 2 11 13" />
    </>
  ),

  clip: (
    <path d="m21.4 11.1-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5" />
  ),

  trash: (
    <>
      <path d="M3 6h18" />
      <path d="M8 6V4h8v2" />
      <path d="m5 6 1 14h12l1-14" />
      <path d="M10 10v6M14 10v6" />
    </>
  ),

  close: <path d="m18 6-12 12M6 6l12 12" />,

  refresh: (
    <>
      <path d="M20 7v5h-5" />
      <path d="M4 17v-5h5" />
      <path d="M5.6 9A7 7 0 0 1 18 6l2 6" />
      <path d="M18.4 15A7 7 0 0 1 6 18l-2-6" />
    </>
  ),

  replace: (
    <>
      <path d="M3 7h13l-3-3" />
      <path d="m16 7-3 3" />
      <path d="M21 17H8l3 3" />
      <path d="m8 17 3-3" />
    </>
  ),
};

export default function Icon({ name, size = 20 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {iconPaths[name] ?? iconPaths.file}
    </svg>
  );
}
