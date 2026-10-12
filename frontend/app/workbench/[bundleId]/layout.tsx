import React from "react";

export default function WorkbenchLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="cc-workbench">
      {children}
    </div>
  );
}
