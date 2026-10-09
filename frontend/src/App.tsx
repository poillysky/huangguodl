import { lazy, Suspense } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useTabSwipe } from "./hooks/useTabSwipe";
import BrowsePage from "./pages/Browse";
import FavoritesPage from "./pages/Favorites";
import MePage from "./pages/Me";
import SearchPage from "./pages/Search";
import SettingsPage from "./pages/Settings";
import ShowDetailPage from "./pages/ShowDetail";
import TaskDetailPage from "./pages/TaskDetail";
import TasksPage from "./pages/Tasks";
import PageLoading from "./components/PageLoading";

const PlayPage = lazy(() => import("./pages/Play"));

export default function App() {
  const loc = useLocation();
  const hideTab = loc.pathname.startsWith("/play/");
  const tabSwipe =
    !hideTab &&
    (loc.pathname === "/huangguo" ||
      loc.pathname === "/huangdou" ||
      loc.pathname === "/yeguo" ||
      loc.pathname === "/me");
  useTabSwipe(tabSwipe);

  return (
    <div className={`app-shell${hideTab ? " play-shell" : ""}`}>
      <Routes>
        <Route path="/" element={<Navigate to="/huangguo" replace />} />
        <Route path="/browse" element={<Navigate to="/huangguo" replace />} />
        <Route path="/huangguo" element={<BrowsePage source="huangguo" />} />
        <Route path="/huangdou" element={<BrowsePage source="huangdou" />} />
        <Route path="/yeguo" element={<BrowsePage source="yeguo" />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/favorites" element={<FavoritesPage />} />
        <Route path="/show/:id" element={<ShowDetailPage />} />
        <Route
          path="/play/:id/:ep"
          element={
            <Suspense fallback={<PageLoading show />}>
              <PlayPage />
            </Suspense>
          }
        />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/tasks/:id" element={<TaskDetailPage />} />
        <Route path="/me" element={<MePage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
      {!hideTab && (
        <nav className="tabbar">
          <NavLink to="/huangguo">黄果</NavLink>
          <NavLink to="/huangdou">黄豆</NavLink>
          <NavLink to="/yeguo">野果</NavLink>
          <NavLink
            to="/me"
            className={({ isActive }) =>
              isActive ||
              loc.pathname.startsWith("/settings") ||
              loc.pathname.startsWith("/favorites") ||
              loc.pathname.startsWith("/tasks")
                ? "active"
                : undefined
            }
          >
            我的
          </NavLink>
        </nav>
      )}
    </div>
  );
}
