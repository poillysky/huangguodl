import { lazy, Suspense } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useTabSwipe } from "./hooks/useTabSwipe";
import BrowsePage from "./pages/Browse";
import FavoritesPage from "./pages/Favorites";
import HomePage from "./pages/Home";
import MePage from "./pages/Me";
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
    (loc.pathname === "/" ||
      loc.pathname === "/browse" ||
      loc.pathname === "/favorites" ||
      loc.pathname === "/tasks" ||
      loc.pathname === "/me");
  useTabSwipe(tabSwipe);

  return (
    <div className={`app-shell${hideTab ? " play-shell" : ""}`}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/browse" element={<BrowsePage />} />
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
          <NavLink to="/" end>
            首页
          </NavLink>
          <NavLink to="/browse">分类</NavLink>
          <NavLink to="/favorites">收藏</NavLink>
          <NavLink to="/tasks">下载</NavLink>
          <NavLink
            to="/me"
            className={({ isActive }) =>
              isActive || loc.pathname.startsWith("/settings") ? "active" : undefined
            }
          >
            我的
          </NavLink>
        </nav>
      )}
    </div>
  );
}
