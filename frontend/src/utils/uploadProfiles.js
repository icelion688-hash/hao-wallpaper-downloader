export const uploadFormatOptions = [
  { value: 'profile', label: '跟随 Profile 默认格式' },
  { value: 'original', label: '原始文件' },
  { value: 'webp', label: 'WebP' },
  { value: 'gif', label: 'GIF（动态图）' },
  { value: 'png', label: 'PNG（静态图）' },
  { value: 'jpg', label: 'JPG（静态图）' },
]

export function createDefaultUploadFilter() {
  return {
    min_width: null,
    min_height: null,
    only_original: false,
  }
}

export function normalizeUploadFormat(value) {
  return uploadFormatOptions.some(item => item.value === value) ? value : 'profile'
}

export function formatUploadFormatLabel(value) {
  return uploadFormatOptions.find(item => item.value === normalizeUploadFormat(value))?.label || '跟随 Profile 默认格式'
}

export function createDefaultUploadProfiles() {
  return [
    {
      key: 'compressed_webp',
      name: '壁纸压缩图床',
      enabled: true,
      base_url: 'https://imgbed.lacexr.com',
      api_token: '',
      channel: 'telegram',
      server_compress: true,
      folder_landscape: 'bg/pc',
      folder_portrait: 'bg/mb',
      folder_dynamic: 'bg/dynamic',
      folder_pattern: '',
      upload_filter: createDefaultUploadFilter(),
      image_processing: {
        enabled: true,
        telegram_only: false,
        format: 'webp',
        quality: 86,
        min_quality: 72,
        threshold_mb: 5,
        target_mb: 4,
        disable_above_mb: 10,
      },
    },
    {
      key: 'original_lossless',
      name: '原图无损图床',
      enabled: false,
      base_url: 'https://imgbed.lacexr.com',
      api_token: '',
      channel: 'huggingface',
      server_compress: false,
      folder_landscape: 'bg/pc',
      folder_portrait: 'bg/mb',
      folder_dynamic: 'bg/dynamic',
      folder_pattern: '',
      upload_filter: { ...createDefaultUploadFilter(), only_original: true },
      image_processing: {
        enabled: false,
        telegram_only: false,
        format: 'original',
        quality: 100,
        min_quality: 100,
        threshold_mb: 5,
        target_mb: 4,
        disable_above_mb: 10,
      },
    },
  ]
}

export function normalizeUploadProfile(profile, baseProfile) {
  return {
    ...baseProfile,
    ...profile,
    image_processing: {
      ...baseProfile.image_processing,
      ...(profile.image_processing || {}),
    },
    upload_filter: {
      ...createDefaultUploadFilter(),
      ...(profile.upload_filter || {}),
    },
  }
}

export function normalizeUploadSettings(remote = {}) {
  const fallbackProfiles = createDefaultUploadProfiles()
  const remoteProfiles = Array.isArray(remote.profiles) && remote.profiles.length
    ? remote.profiles
    : fallbackProfiles

  const profiles = remoteProfiles.map((profile, index) => {
    const baseProfile = fallbackProfiles.find(item => item.key === profile.key) || fallbackProfiles[index] || fallbackProfiles[0]
    return normalizeUploadProfile(profile, baseProfile)
  })

  return {
    task_profile: remote.task_profile || profiles[0]?.key || fallbackProfiles[0].key,
    gallery_default_format: normalizeUploadFormat(remote.gallery_default_format),
    profiles,
  }
}

export function isLosslessUploadProfile(profile) {
  return profile?.image_processing?.format === 'original' || !profile?.image_processing?.enabled
}

export function applyLosslessUploadProfile(profile) {
  if (!profile?.image_processing) return
  profile.server_compress = false
  profile.image_processing.enabled = false
  profile.image_processing.format = 'original'
}

export function applyCompressedUploadProfile(profile) {
  if (!profile?.image_processing) return
  profile.image_processing.enabled = true
  profile.image_processing.format = 'webp'
}
