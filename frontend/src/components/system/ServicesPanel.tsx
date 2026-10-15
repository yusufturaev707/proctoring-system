import { Box, Grid, Stack, Table, TableBody, TableCell, TableHead, TableRow, Tooltip, Typography } from '@mui/material'
import ServiceIcon from '@mui/icons-material/AccountTreeOutlined'
import ComputerIcon from '@mui/icons-material/ComputerOutlined'

import { bytes, duration, num, pct, VIRT_LABEL } from './format'
import type { Level } from './format'
import { Dot, LevelChip, Metric, MetricGrid, Mono, SectionCard, Unavailable } from './parts'
import type { ApiRecord } from '../../types/api'

const GROUP_LABEL: Record<string, string> = { app: 'Ilova', infra: 'Infratuzilma', vm: 'Virtual mashina' }

function unitLevel(unit: ApiRecord): Level {
  if (unit.load_state === 'not-found') return 'critical'
  if (unit.active_state === 'active') return unit.restarts ? 'warning' : 'ok'
  if (unit.active_state === 'activating' || unit.active_state === 'reloading') return 'warning'
  return unit.required ? 'critical' : 'warning'
}

function unitLabel(unit: ApiRecord): string {
  if (unit.load_state === 'not-found') return 'Topilmadi'
  if (unit.active_state === 'active') return unit.sub_state === 'running' ? 'Ishlayapti' : unit.sub_state
  if (unit.active_state === 'failed') return 'Yiqilgan'
  if (unit.active_state === 'inactive') return 'To‘xtagan'
  return unit.active_state
}

export default function ServicesPanel({ status }: { status: ApiRecord }) {
  const services = status.services || {}
  const units: ApiRecord[] = services.units || []
  const host = status.host || {}
  const virt = host.virtualization || {}
  const timeSync = host.time_sync || {}
  const down = units.filter((unit) => unitLevel(unit) === 'critical').length

  return (
    <Grid container spacing={{ xs: 1.5, sm: 2.5 }}>
      <Grid item xs={12} xl={8}>
        <SectionCard
          icon={ServiceIcon}
          title="systemd servislari"
          subtitle="Holat, qayta ishga tushishlar, CPU (100% = bitta yadro) va xotira"
          level={down ? 'critical' : undefined}
        >
          {!services.available ? (
            <Unavailable>
              systemd mavjud emas (dev muhit — Windows). Production’da (Debian) bu yerda
              `proctoring-*`, nginx, PostgreSQL va Redis servislari ko‘rinadi.
            </Unavailable>
          ) : (
            <Box sx={{ overflowX: 'auto', mx: { xs: -2, sm: 0 } }}>
              <Table size="small" sx={{ minWidth: 720 }}>
                <TableHead>
                  <TableRow>
                    <TableCell>Servis</TableCell>
                    <TableCell>Holat</TableCell>
                    <TableCell align="right">Ishlayapti</TableCell>
                    <TableCell align="right">Qayta ishga tushgan</TableCell>
                    <TableCell align="right">CPU</TableCell>
                    <TableCell align="right">Xotira</TableCell>
                    <TableCell align="right">Thread</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {units.map((unit) => {
                    const level = unitLevel(unit)
                    return (
                      <TableRow key={unit.unit} hover>
                        <TableCell>
                          <Stack direction="row" spacing={1.25} alignItems="center">
                            <Dot level={level} pulse={level === 'critical'} />
                            <Box sx={{ minWidth: 0 }}>
                              <Typography variant="body2" fontWeight={600} noWrap>{unit.label}</Typography>
                              <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>
                                <Mono>{unit.unit}</Mono> · {GROUP_LABEL[unit.group] || unit.group}
                              </Typography>
                            </Box>
                          </Stack>
                        </TableCell>
                        <TableCell><LevelChip level={level} label={unitLabel(unit)} /></TableCell>
                        <TableCell align="right">{duration(unit.uptime_s)}</TableCell>
                        <TableCell align="right" sx={{ color: unit.restarts ? 'warning.main' : 'text.disabled', fontWeight: unit.restarts ? 700 : 400 }}>
                          {num(unit.restarts)}
                        </TableCell>
                        <TableCell align="right">{pct(unit.cpu_pct)}</TableCell>
                        <TableCell align="right">{bytes(unit.memory)}</TableCell>
                        <TableCell align="right">{num(unit.tasks)}</TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </Box>
          )}
        </SectionCard>
      </Grid>
      <Grid item xs={12} xl={4}>
        <SectionCard icon={ComputerIcon} title="Server" subtitle={host.os}>
          <MetricGrid min={150}>
            <Metric label="Xost nomi" value={host.hostname || '—'} />
            <Metric
              label="Virtualizatsiya"
              value={virt.type ? (VIRT_LABEL[virt.type] || virt.type) : 'Fizik / aniqlanmadi'}
              hint={virt.product || undefined}
            />
            {virt.type === 'vmware' && (
              <Metric
                label="VMware Tools"
                value={virt.vmware_tools ? 'Ishlayapti' : 'Ishlamayapti'}
                level={virt.vmware_tools ? 'ok' : 'warning'}
                tooltip="open-vm-tools: xostdan to‘g‘ri o‘chirish, vaqt sinxronizatsiyasi, xotira boshqaruvi"
              />
            )}
            <Metric label="Yadro (kernel)" value={host.kernel || '—'} />
            <Metric label="vCPU" value={`${num(host.cpu_logical)} (fizik ${num(host.cpu_physical)})`} hint={host.cpu_model} />
            <Metric label="Ishlayapti" value={duration(host.uptime_s)} />
            <Metric
              label="Vaqt sinxronizatsiyasi"
              value={!timeSync.available ? '—' : timeSync.synced ? 'Sinxron (NTP)' : 'Sinxron EMAS'}
              hint={timeSync.timezone || undefined}
              level={timeSync.synced === false ? 'warning' : undefined}
            />
            <Metric label="Python" value={host.python || '—'} />
          </MetricGrid>
          {virt.type === 'vmware' && (
            <Tooltip title="ESXi'da VM resurslari xost bilan bo'lishiladi: steal va disk kechikishi shu yerdan keladi.">
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
                VM ichidan ko‘rinmaydigan sabablar (xost band, datastore sekin) — «Protsessor: steal» va
                «Disk: javob vaqti» ko‘rsatkichlarida.
              </Typography>
            </Tooltip>
          )}
        </SectionCard>
      </Grid>
    </Grid>
  )
}
