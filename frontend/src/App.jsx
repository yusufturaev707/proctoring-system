import { lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Box, CircularProgress } from '@mui/material'

import AppLayout from './layout/AppLayout'
import Login from './pages/Login'
import { NAVIGATION, ROUTE_LOADERS } from './layout/navigation'
import { ForbiddenState, RegionMissingState } from './components/feedback/States'
import { useAuth } from './context/AuthContext'

// Sahifalar `ROUTE_LOADERS` dan olinadi — bir joyda saqlangani menyu
// prefetch'i bilan bir xil chunk'ni ishlatishni kafolatlaydi.
const Dashboard = lazy(ROUTE_LOADERS['/'])
const LiveMonitor = lazy(ROUTE_LOADERS['/live'])
const Sessions = lazy(ROUTE_LOADERS['/sessions'])
const SessionDetail = lazy(() => import('./pages/SessionDetail'))
const TechnicalProblems = lazy(ROUTE_LOADERS['/technical-problems'])
const RegionsPage = lazy(ROUTE_LOADERS['/regions'])
const ZonesPage = lazy(ROUTE_LOADERS['/zones'])
const ComputersPage = lazy(ROUTE_LOADERS['/computers'])
const CamerasPage = lazy(ROUTE_LOADERS['/cameras'])
const DeviceTokens = lazy(ROUTE_LOADERS['/device-tokens'])
const ExamTypesPage = lazy(ROUTE_LOADERS['/exam-types'])
const ExamsPage = lazy(ROUTE_LOADERS['/exams'])
const ExamSchedulesPage = lazy(ROUTE_LOADERS['/exam-schedules'])
const ComputerBookings = lazy(ROUTE_LOADERS['/computer-bookings'])
const Users = lazy(ROUTE_LOADERS['/users'])
const Roles = lazy(ROUTE_LOADERS['/roles'])
const Settings = lazy(ROUTE_LOADERS['/settings'])
const AllowedIpsPage = lazy(ROUTE_LOADERS['/allowed-ips'])
const ClientExitPasswordsPage = lazy(ROUTE_LOADERS['/exit-passwords'])
const RdpObjectsPage = lazy(ROUTE_LOADERS['/rdp-objects'])
const HotkeysPage = lazy(ROUTE_LOADERS['/hotkeys'])
const CocoObjectsPage = lazy(ROUTE_LOADERS['/coco-objects'])
const CocoGroupsPage = lazy(ROUTE_LOADERS['/coco-groups'])
const ModelVersionsPage = lazy(ROUTE_LOADERS['/model-versions'])
const ProctoringPoliciesPage = lazy(ROUTE_LOADERS['/proctoring-policies'])
const RiskWeightsPage = lazy(ROUTE_LOADERS['/risk-weights'])
const AuditLogs = lazy(ROUTE_LOADERS['/audit'])
const Profile = lazy(ROUTE_LOADERS['/profile'])

function RequireAuth({ children }) {
  const { isAuthenticated, loading } = useAuth()
  if (loading) {
    return (
      <Box sx={{ display: 'grid', placeItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    )
  }
  return isAuthenticated ? children : <Navigate to="/login" replace />
}

/**
 * Ruxsat to'sig'i.
 *
 * DIQQAT: bu faqat UI qulayligi — foydalanuvchi ishlata olmaydigan
 * bo'limni ko'rmasligi uchun. Haqiqiy himoya backendda (`HasRolePermission`).
 * Bu komponentni chetlab o'tish DevTools'da bir necha soniyalik ish.
 */
function Guard({ permission, children }) {
  const { can, lacksRegion } = useAuth()
  // Viloyatsiz viloyat xodimi — sabab ruxsatda emas, hisobda. Server
  // baribir hech narsa bermaydi (`region_not_assigned`), bo'sh jadval va
  // qizil xatolar o'rniga bitta tushunarli ekran.
  if (lacksRegion) return <RegionMissingState />
  return can(permission) ? children : <ForbiddenState permission={permission} />
}

/**
 * Bosh sahifa — ruxsatga qarab.
 *
 * `/` Boshqaruv paneli (`dashboard.view`). Operator va Kuzatuvchi kabi
 * rollarda u yo'q va ilgari login'dan keyin birinchi ko'rinadigan narsa
 * «Ruxsat yo'q» ekrani edi. Endi — menyudagi birinchi ruxsat berilgan
 * sahifa (menyu tartibi — ish tartibi).
 */
function Home() {
  const { can, lacksRegion } = useAuth()
  if (lacksRegion) return <RegionMissingState />
  if (can('dashboard.view')) return <Dashboard />
  const first = NAVIGATION.flatMap((group) => group.items).find((item) => can(item.permission))
  return first ? <Navigate to={first.path} replace /> : <ForbiddenState />
}

const ROUTES = [
  { path: '/', element: <Home />, permission: null },
  { path: '/live', element: <LiveMonitor />, permission: 'sessions.view' },
  { path: '/sessions', element: <Sessions />, permission: 'sessions.view' },
  { path: '/sessions/:id', element: <SessionDetail />, permission: 'sessions.view' },
  { path: '/technical-problems', element: <TechnicalProblems />, permission: 'technical.view' },
  { path: '/regions', element: <RegionsPage />, permission: 'regions.view' },
  { path: '/zones', element: <ZonesPage />, permission: 'regions.view' },
  { path: '/computers', element: <ComputersPage />, permission: 'devices.view' },
  { path: '/cameras', element: <CamerasPage />, permission: 'devices.view' },
  { path: '/device-tokens', element: <DeviceTokens />, permission: 'devices.view' },
  { path: '/exam-types', element: <ExamTypesPage />, permission: 'exams.view' },
  { path: '/exams', element: <ExamsPage />, permission: 'exams.view' },
  { path: '/exam-schedules', element: <ExamSchedulesPage />, permission: 'exams.view' },
  { path: '/computer-bookings', element: <ComputerBookings />, permission: 'bookings.view' },
  { path: '/users', element: <Users />, permission: 'users.view' },
  { path: '/roles', element: <Roles />, permission: 'users.view' },
  { path: '/settings', element: <Settings />, permission: 'controls.view' },
  { path: '/allowed-ips', element: <AllowedIpsPage />, permission: 'controls.ip_view' },
  { path: '/exit-passwords', element: <ClientExitPasswordsPage />, permission: 'controls.exit_password_view' },
  { path: '/rdp-objects', element: <RdpObjectsPage />, permission: 'controls.view' },
  { path: '/hotkeys', element: <HotkeysPage />, permission: 'controls.view' },
  { path: '/coco-objects', element: <CocoObjectsPage />, permission: 'controls.view' },
  { path: '/coco-groups', element: <CocoGroupsPage />, permission: 'controls.view' },
  { path: '/model-versions', element: <ModelVersionsPage />, permission: 'controls.view' },
  {
    path: '/proctoring-policies',
    element: <ProctoringPoliciesPage />,
    permission: 'controls.proctoring_view',
  },
  { path: '/risk-weights', element: <RiskWeightsPage />, permission: 'controls.proctoring_view' },
  { path: '/audit', element: <AuditLogs />, permission: 'audit.view' },
  { path: '/profile', element: <Profile />, permission: null },
]

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        {ROUTES.map((route) => (
          <Route
            key={route.path}
            path={route.path}
            element={
              route.permission
                ? <Guard permission={route.permission}>{route.element}</Guard>
                : route.element
            }
          />
        ))}
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
