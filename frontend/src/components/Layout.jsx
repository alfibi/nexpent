import { useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Sparkles, Target, ClipboardList, Home, BarChart2, Landmark, UserRound } from 'lucide-react';
import { prefetchAppData } from "../lib/resourceCache";

export default function Layout() {
  const location = useLocation();

  useEffect(() => prefetchAppData(), []);
  
  // Hide layout wrappers on Auth page
  if (location.pathname === "/auth") {
    return <Outlet />;
  }

  const navItems = [
    { path: "/", label: "Home", icon: <Home size={20} /> },
    { path: "/accounts", label: "Accounts", icon: <Landmark size={20} /> },
    { path: "/ledger", label: "Ledger", icon: <ClipboardList size={20} /> },
    { path: "/planner", label: "Planner", icon: <BarChart2 size={20} /> },
    { path: "/goals", label: "Goals", icon: <Target size={20} /> },
    { path: "/advisor", label: "AI", icon: <Sparkles size={20} /> },
    { path: "/profile", label: "Profile", icon: <UserRound size={20} /> },
  ];
  const bottomNavItems = navItems.filter((item) =>
    ["/", "/accounts", "/ledger", "/planner", "/profile"].includes(item.path)
  );

  return (
    <div className="layout-wrapper">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">M$</div>
          <div className="sidebar-logo-text">MoneyHub</div>
        </div>
        <nav>
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/"}
              className={({ isActive }) =>
                `sidebar-item ${isActive ? "active" : ""}`
              }
            >
              <div className="nav-icon">{item.icon}</div>
              <div>{item.label}</div>
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="screen">
        <Outlet />
      </main>

      <nav className="bottom-nav">
        {bottomNavItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === "/"}
            className={({ isActive }) =>
              `nav-item ${isActive ? "active" : ""}`
            }
          >
            <div className="nav-icon">{item.icon}</div>
            <div className="nav-label">{item.label}</div>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
