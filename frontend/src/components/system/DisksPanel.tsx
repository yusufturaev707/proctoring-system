import { useTheme } from '@mui/material/styles'
import { Box, Chip, Grid, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material'
import DiskIcon from '@mui/icons-material/StorageOutlined'
import SpeedIcon from '@mui/icons-material/ShutterSpeedOutlined'
import PhotoIcon from '@mui/icons-material/PhotoLibraryOutlined'

import { byteRate, bytes, DATA_LABEL, duration, levelOf, ms, num, pct, worst } from './format'
import { levelColor, Meter, Metric, MetricGrid, Mono, SectionCard, Unavailable } from './parts'
import type { ApiRecord } from '../../types/api'

function MountRow({ mount, thresholds }: { mount: ApiRecord; thresholds: ApiRecord }) {
  return (
    <Box sx={{ p: 2, borderRadius: '16px', border: 1, borderColor: 'm3.outlineVariant' }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} justifyContent="space-between" alignItems={{ sm: 'center' }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle2" fontWeight={700}><Mono>{mount.mount}</Mono></Typography>
          <Typography variant="caption" color="text.secondary">
            <Mono>{mount.device}</Mono> · {mount.fstype}
          </Typography>
        </Box>
        <Stack direction="row" flexWrap="wrap" useFlexGap gap={0.75}>
          {(mount.contains || []).map((name: string) => (
            <Chip key={name} size="small" label={DATA_LABEL[name] || name} sx={{ bgcolor: 'm3.secondaryContainer', color: 'm3.onSecondaryContainer' }} />
          ))}
        </Stack>
      </Stack>
      <Box sx={{ mt: 1.5 }}>
        <Meter value={mount.percent} level={levelOf(thresholds, 'disk_pct', mount.percent)} height={10} />
      </Box>
      <Stack direction="row" justifyContent="space-between" sx={{ mt: 0.75 }}>
        <Typography variant="caption" color="text.secondary">
          {bytes(mount.used)} / {bytes(mount.total)} band
        </Typography>
        <Typography variant="caption" fontWeight={700}>
          {pct(mount.percent)} · {bytes(mount.free)} bo‘sh
        </Typography>
      </Stack>
      <Box sx={{ mt: 1.5 }}>
        <MetricGrid min={120}>
          <Metric
            label="Inode (fayllar soni)"
            value={pct(mount.inodes_percent)}
            level={levelOf(thresholds, 'inode_pct', mount.inodes_percent)}
            tooltip="Juda ko'p mayda fayl (skrinshot) — joy bo'lsa ham yangi fayl yozilmaydi"
          />
          <Metric
            label="Kunlik o‘sish"
            value={mount.growth_per_day != null ? `${mount.growth_per_day >= 0 ? '+' : ''}${bytes(mount.growth_per_day)}` : '—'}
            hint="oxirgi ≤ 14 kun"
          />
          <Metric
            label="To‘lishiga"
            value={mount.days_left != null ? `~${num(mount.days_left)} kun` : '—'}
            hint={mount.days_left != null ? undefined : 'kamida 1 kunlik tarix kerak'}
            level={levelOf(thresholds, 'disk_days_left', mount.days_left)}
          />
        </MetricGrid>
      </Box>
    </Box>
  )
}

export default function DisksPanel({ status }: { status: ApiRecord }) {
  const theme = useTheme()
  const thresholds = status.thresholds
  const mounts: ApiRecord[] = status.disks?.mounts || []
  const io: ApiRecord[] = status.disks?.io || []
  const storage = status.storage
  const diskLevel = worst(...mounts.map((mount) => levelOf(thresholds, 'disk_pct', mount.percent)))

  return (
    <Grid container spacing={{ xs: 1.5, sm: 2.5 }}>
      <Grid item xs={12} lg={7}>
        <SectionCard icon={DiskIcon} title="Fayl tizimlari" subtitle="Band joy, inode va to‘lish prognozi" level={diskLevel}>
          <Stack spacing={1.5}>
            {mounts.length ? mounts.map((mount) => <MountRow key={mount.mount} mount={mount} thresholds={thresholds} />)
              : <Unavailable>Disk ma’lumoti o‘qilmadi.</Unavailable>}
          </Stack>
        </SectionCard>
      </Grid>
      <Grid item xs={12} lg={5}>
        <Stack spacing={{ xs: 1.5, sm: 2.5 }}>
          <SectionCard icon={SpeedIcon} title="Disk kiritish/chiqarish" subtitle="iostat: tezlik, IOPS, bandlik, javob vaqti">
            {!io.length ? <Unavailable>Qurilma statistikasi yo‘q.</Unavailable> : (
              <Box sx={{ overflowX: 'auto', mx: { xs: -2, sm: 0 } }}>
                <Table size="small" sx={{ minWidth: 460, '& td, & th': { whiteSpace: 'nowrap' } }}>
                  <TableHead>
                    <TableRow>
                      <TableCell>Qurilma</TableCell>
                      <TableCell align="right">O‘qish</TableCell>
                      <TableCell align="right">Yozish</TableCell>
                      <TableCell align="right">IOPS</TableCell>
                      <TableCell align="right">Band</TableCell>
                      <TableCell align="right">Javob</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {io.map((device) => {
                      const util = levelOf(thresholds, 'disk_util_pct', device.util_pct)
                      const wait = levelOf(thresholds, 'disk_await_ms', device.await_ms)
                      return (
                        <TableRow key={device.device}>
                          <TableCell><Mono>{device.device}</Mono></TableCell>
                          <TableCell align="right">{byteRate(device.read_bps)}</TableCell>
                          <TableCell align="right">{byteRate(device.write_bps)}</TableCell>
                          <TableCell align="right">{num((device.read_iops || 0) + (device.write_iops || 0), 0)}</TableCell>
                          <TableCell align="right" sx={{ color: util === 'ok' || util === 'unknown' ? undefined : levelColor(theme, util), fontWeight: 600 }}>
                            {pct(device.util_pct, 0)}
                          </TableCell>
                          <TableCell align="right" sx={{ color: wait === 'ok' || wait === 'unknown' ? undefined : levelColor(theme, wait), fontWeight: 600 }}>
                            {ms(device.await_ms)}
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </Box>
            )}
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
              ESXi’da javob vaqti {'>'} 20 ms — datastore band (boshqa VM’lar, snapshot’lar).
            </Typography>
          </SectionCard>

          <SectionCard
            icon={PhotoIcon}
            title="Rasmlar va dalillar"
            subtitle={storage ? `Hisoblangan: ${duration(Date.now() / 1000 - storage.computed_at)} oldin` : 'Soatiga bir marta hisoblanadi'}
          >
            {!storage ? (
              <Unavailable>
                Hajm hali hisoblanmagan — `monitoring.sample_system` vazifasi birinchi yurishda hisoblaydi.
              </Unavailable>
            ) : (
              <>
                <MetricGrid min={150}>
                  <Metric
                    label="Skrinshotlar"
                    value={bytes(storage.screenshots?.bytes)}
                    hint={`${num(storage.screenshots?.count)} ta fayl`}
                  />
                  <Metric
                    label="Bugun"
                    value={`+${bytes(storage.screenshots?.today_bytes)}`}
                    hint={`${num(storage.screenshots?.today_count)} ta skrinshot`}
                  />
                  <Metric label="Dalil kadrlari" value={bytes(storage.evidence?.bytes)} hint={`${num(storage.evidence?.count)} ta`} />
                  <Metric label="FaceID kadrlari" value={num(storage.face_images?.count)} hint="hajmi bazada yo‘q" />
                  {storage.s3_screenshots?.count > 0 && (
                    <Metric label="S3 skrinshotlar" value={bytes(storage.s3_screenshots?.bytes)} hint={`${num(storage.s3_screenshots?.count)} ta`} />
                  )}
                </MetricGrid>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
                  Ildiz: <Mono>{storage.root}</Mono>
                </Typography>
              </>
            )}
          </SectionCard>
        </Stack>
      </Grid>
    </Grid>
  )
}
